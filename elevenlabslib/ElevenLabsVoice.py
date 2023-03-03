from __future__ import annotations

import io
import os
import queue

import threading
from typing import BinaryIO, Optional

import soundfile as sf
import sounddevice as sd

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elevenlabslib.ElevenLabsSample import ElevenLabsSample
    from elevenlabslib.ElevenLabsUser import ElevenLabsUser
from elevenlabslib.helpers import *

playbackBlockSize = 2048
downloadChunkSize = 4096
playbackBufferSizeInBlocks = 20

class ElevenLabsVoice:
    """
    Represents a voice in the ElevenLabs API.
    It's the parent class for all voices, and used directly for the premade ones.
    """
    @staticmethod
    def voiceFactory(voiceData, linkedUser: ElevenLabsUser) -> ElevenLabsVoice | ElevenLabsGeneratedVoice | ElevenLabsClonedVoice:
        """
        Initializes a new instance of either ElevenLabsVoice or ElevenLabsGeneratedVoice or ElevenLabsClonedVoice depending on the category.
        Args:
            voiceData: A dictionary containing the voice data.
            linkedUser: An instance of the ElevenLabsUser class representing the linked user.
        """
        if voiceData["category"] == "premade":
            return ElevenLabsVoice(voiceData, linkedUser)
        elif voiceData["category"] == "cloned":
            return ElevenLabsClonedVoice(voiceData, linkedUser)
        elif voiceData["category"] == "generated":
            return ElevenLabsGeneratedVoice(voiceData, linkedUser)
        else:
            raise ValueError(voiceData["category"] + " is not a valid voice category!")

    def __init__(self, voiceData, linkedUser:ElevenLabsUser):
        """
        Initializes a new instance of the ElevenLabsVoice class.
        Don't use this constructor directly. Use the factory instead.
        Args:
            voiceData: A dictionary containing the voice data.
            linkedUser: An instance of the ElevenLabsUser class representing the linked user.
        """
        self._linkedUser = linkedUser
        # This is the name at the time the object was created. It won't be updated.
        # (Useful to iterate over all voices to find one with a specific name without spamming the API)
        self.initialName = voiceData["name"]
        self._voiceID = voiceData["voice_id"]
        self._category = voiceData["category"]
        self._labels = voiceData["labels"]

        self._q = queue.Queue(maxsize=playbackBufferSizeInBlocks)
        self._bytesFile = io.BytesIO()
        self._bytesSoundFile: Optional[sf.SoundFile] = None    #Needs to be created later.
        self._bytesLock = threading.Lock()

        self._events:dict[str, threading.Event] = {
            "playbackFinishedEvent" : threading.Event(),
            "headerReadyEvent" : threading.Event(),
            "soundFileReadyEvent" : threading.Event(),
            "downloadDoneEvent" : threading.Event(),
            "blockDataAvailable" : threading.Event()
        }

    def _generate_payload(self, prompt:str, stability:Optional[float]=None, similarity_boost:Optional[float]=None) -> dict:
        """
        Generates the payload for the text-to-speech API call.

        Args:
            prompt (str): The prompt to generate speech for.
            stability (Optional[float]): A float between 0 and 1 representing the stability of the generated audio. If None, the current stability setting is used.
            similarity_boost (Optional[float]): A float between 0 and 1 representing the similarity boost of the generated audio. If None, the current similarity boost setting is used.

        Returns:
            dict: A dictionary representing the payload for the API call.
        """
        payload = {"text": prompt}
        if stability is not None or similarity_boost is not None:
            currentSettings = self.get_settings()
            if stability is None: stability = currentSettings["stability"]
            if similarity_boost is None: similarity_boost = currentSettings["similarity_boost"]
            if not (0 <= stability <= 1 and 0 <= similarity_boost <= 1):
                raise ValueError("Please provide a value between 0 and 1.")
            payload["voice_settings"] = dict()
            payload["voice_settings"]["stability"] = stability
            payload["voice_settings"]["similarity_boost"] = similarity_boost
        return payload

    def generate_audio_bytes(self, prompt:str, stability:Optional[float]=None, similarity_boost:Optional[float]=None) -> bytes:
        """
        Generates speech for the given prompt and returns the audio data as bytes of an mp3 file.

        Args:
        	prompt: The prompt to generate speech for.
        	stability: A float between 0 and 1 representing the stability of the generated audio. If None, the current stability setting is used.
        	similarity_boost: A float between 0 and 1 representing the similarity boost of the generated audio. If None, the current similarity boost setting is used.

        Returns:
        	A bytes object representing the generated audio data.
        """
        #The output from the site is an mp3 file.
        #You can check the README for an example of how to convert it to wav on the fly using pydub and bytesIO.
        payload = self._generate_payload(prompt, stability, similarity_boost)
        response = api_json("/text-to-speech/" + self._voiceID + "/stream", self._linkedUser.headers, jsonData=payload)


        return response.content

    def generate_and_play_audio(self, prompt:str, playInBackground:bool, portaudioDeviceID:Optional[int] = None, stability:Optional[float]=None, similarity_boost:Optional[float]=None) -> None:
        """
        Generate audio bytes from the given prompt and play them using sounddevice.

        Parameters:
        	prompt (str): The text prompt to generate audio from.
        	playInBackground (bool): Whether to play audio in the background or wait for it to finish playing.
        	portaudioDeviceID (int, optional): The ID of the audio device to use for playback. Defaults to the default output device.
        	stability: A float between 0 and 1 representing the stability of the generated audio. If None, the current stability setting is used.
        	similarity_boost: A float between 0 and 1 representing the similarity boost of the generated audio. If None, the current similarity boost setting is used.

        Returns:
        None
        """
        play_audio_bytes(self.generate_audio_bytes(prompt, stability, similarity_boost), playInBackground, portaudioDeviceID)
        return

    def generate_and_stream_audio(self,prompt:str, portaudioDeviceID:Optional[int] = None, stability:Optional[float]=None, similarity_boost:Optional[float]=None):
        """
        Generate audio bytes from the given prompt and play them using sounddevice in callback mode.
        It is always blocking, and can sometimes make the audio skip slightly, but the audio begins playing much more quickly.
        Parameters:
        	prompt (str): The text prompt to generate audio from.
        	portaudioDeviceID (int, optional): The ID of the audio device to use for playback. Defaults to the default output device.
        	stability: A float between 0 and 1 representing the stability of the generated audio. If None, the current stability setting is used.
        	similarity_boost: A float between 0 and 1 representing the similarity boost of the generated audio. If None, the current similarity boost setting is used.

        Returns:
        None
        """
        #Clean all the buffers and reset all events.
        self._q = queue.Queue(maxsize=playbackBufferSizeInBlocks)
        self._bytesFile = io.BytesIO()
        self._bytesSoundFile: Optional[sf.SoundFile] = None  # Needs to be created later.
        for eventName, event in self._events.items():
            event.clear()

        payload = self._generate_payload(prompt, stability, similarity_boost)
        path = "/text-to-speech/" + self._voiceID + "/stream"
        if portaudioDeviceID is None:
            portaudioDeviceID = sd.default.device

        downloadThread = threading.Thread(target=self._stream_downloader_function, args=(path, payload))
        downloadThread.start()

        while True:
            logging.debug("Waiting for header event...")
            self._events["headerReadyEvent"].wait()
            logging.debug("Header maybe ready?")
            try:
                with self._bytesLock:
                    self._bytesSoundFile = sf.SoundFile(self._bytesFile)
                    logging.debug("File created (" + str(self._bytesFile.tell()) + " bytes read).")
                    self._events["soundFileReadyEvent"].set()
                    break
            except sf.LibsndfileError:
                self._bytesFile.seek(0)
                dataBytes = self._bytesFile.read()
                self._bytesFile.seek(0)
                logging.debug("Error creating the soundfile with " + str(len(dataBytes)) + " bytes of data. Let's clear the headerReady event.")
                self._events["headerReadyEvent"].clear()
                self._events["soundFileReadyEvent"].set()

        stream = sd.RawOutputStream(
            samplerate=self._bytesSoundFile.samplerate, blocksize=playbackBlockSize,
            device=portaudioDeviceID, channels=self._bytesSoundFile.channels, dtype='float32',
            callback=self._stream_playback_callback, finished_callback=self._events["playbackFinishedEvent"].set)
        logging.debug("Starting playback...")
        with stream:
            timeout = playbackBlockSize * playbackBufferSizeInBlocks / self._bytesSoundFile.samplerate
            # data = getDataFromDownload(bytesSoundFile)
            while True:
                data = self._insert_into_queue_from_download_thread()
                if data != b"":
                    logging.debug("Putting " + str(len(data)) + " bytes in queue.")
                    self._q.put(data, timeout=timeout)
                else:
                    logging.debug("Got back no data, let's not write that to the queue...")
                    with self._bytesLock:
                        oldPos = self._bytesFile.tell()
                        endPos = self._bytesFile.seek(0, os.SEEK_END)
                        self._bytesFile.seek(oldPos)
                        if endPos == oldPos and self._events["downloadDoneEvent"].is_set():
                            break
            logging.debug("While loop done.")
            self._events["playbackFinishedEvent"].wait()  # Wait until playback is finished
            logging.debug(stream.active)
        logging.debug("Stream done.")

        return

    def _stream_downloader_function(self, path, payload):
        # This is the function running in the download thread.
        #testURL = ""
        #streamedRequest = requests.get(testURL, stream=True)
        streamedRequest = requests.post(api_endpoint + path, headers=self._linkedUser.headers, json=payload, stream=True)

        streamedRequest.raise_for_status()
        totalLength = 0
        logging.debug("Starting iter...")
        for chunk in streamedRequest.iter_content(chunk_size=downloadChunkSize):
            if self._events["headerReadyEvent"].is_set():
                logging.debug("HeaderReady is set, waiting for the soundfile...")
                self._events["soundFileReadyEvent"].wait()  # Wait for the soundfile to be created.
                if not self._events["headerReadyEvent"].is_set():
                    logging.debug("headerReady was cleared by the playback thread. Header data still missing, download more.")
                    self._events["soundFileReadyEvent"].clear()

            totalLength += len(chunk)
            if len(chunk) != downloadChunkSize:
                logging.debug("Writing weirdly sized chunk (" + str(len(chunk)) + ")...")

            # Write the new data then seek back to the initial position.
            with self._bytesLock:
                if not self._events["headerReadyEvent"].is_set():
                    logging.debug("headerReady not set, setting it...")
                    self._bytesFile.seek(0, os.SEEK_END)  # MAKE SURE the head is at the end.
                    self._bytesFile.write(chunk)
                    self._bytesFile.seek(0)  # Move the head back.
                    self._events["headerReadyEvent"].set()  # We've never downloaded a single chunk before. Do that and move the head back, then fire the event.
                else:
                    lastReadPos = self._bytesFile.tell()
                    lastWritePos = self._bytesFile.seek(0, os.SEEK_END)
                    self._bytesFile.write(chunk)
                    endPos = self._bytesFile.tell()
                    self._bytesFile.seek(lastReadPos)
                    logging.debug("Write head move: " + str(endPos - lastWritePos))
                    if endPos - lastReadPos > playbackBlockSize:  # We've read enough data to fill up a block, alert the other thread.
                        logging.debug("Raise available data event - " + str(endPos - lastReadPos) + " bytes available")
                        self._events["blockDataAvailable"].set()

        logging.debug("Download finished - " + str(totalLength) + ".")
        self._events["downloadDoneEvent"].set()
        self._events["blockDataAvailable"].set()  # Ensure that the other thread knows data is available
        return

    def _stream_playback_callback(self, outdata, frames, timeData, status):
        assert frames == playbackBlockSize
        if status.output_underflow:
            logging.error('Output underflow: increase blocksize?')
            raise sd.CallbackAbort
        assert not status

        while True:
            try:
                readData = self._q.get_nowait()
                if len(readData) == 0 and not self._events["downloadDoneEvent"].is_set():
                    logging.debug("An empty item got into the queue. Skip it.")
                    continue
                break
            except queue.Empty as e:
                if self._events["downloadDoneEvent"].is_set():
                    logging.debug("Download (and playback) finished.")  # We're done.
                    raise sd.CallbackStop
                else:
                    # This should NEVER happen, as the getdownloaddata function handles waiting for new data to come in. ABORT.
                    logging.debug("Missing data but download isn't over. What the fuck?")
                    raise sd.CallbackAbort

        # Last read chunk was smaller than it should've been. It's either EOF or that stupid soundFile bug.
        if 0 < len(readData) < len(outdata):
            logging.debug("Data read smaller than it should've been.")
            logging.debug("Read " + str(len(readData)) + " bytes but expected " + str(len(outdata)) + ", padding...")

            # I still don't really understand why this happens - seems to be related to the soundfile bug.
            # Padding it like this means there ends up being a small portion of silence during the playback.

            outdata[:len(readData)] = readData
            outdata[len(readData):] = b'\x00' * (len(outdata) - len(readData))
        elif len(readData) == 0:
            logging.debug("Callback got no data from the queue. Checking if playback is over...")
            with self._bytesLock:
                oldPos = self._bytesFile.tell()
                endPos = self._bytesFile.seek(0, os.SEEK_END)
                if oldPos == endPos and self._events["downloadDoneEvent"].is_set():
                    logging.debug("EOF reached and download over! Stopping callback...")
                    raise sd.CallbackStop
                else:
                    logging.debug("...Read no data but the download isn't over, what the fuck? Panic. Just send silence.")
                    outdata[len(readData):] = b'\x00' * (len(outdata) - len(readData))
        else:
            outdata[:] = readData
    #THIS FUNCTION ASSUMES YOU'VE GIVEN THE THREAD THE LOCK.
    def _soundFile_read_and_fix(self, dataToRead:int=-1, dtype="float32"):
        readData = self._bytesSoundFile.buffer_read(dataToRead, dtype=dtype)
        if len(readData) == 0:
            logging.debug("No data read.")
            logging.debug("Frame counter must be outdated, recreating soundfile...")
            self._bytesFile.seek(0)
            newSF = sf.SoundFile(self._bytesFile)
            newSF.seek(self._bytesSoundFile.tell())
            self._bytesSoundFile = newSF
            readData = self._bytesSoundFile.buffer_read(dataToRead, dtype=dtype)
            logging.debug("Now read " + str(len(readData)) + " bytes. I sure fucking hope that number isn't zero.")
        return readData

    def _insert_into_queue_from_download_thread(self) -> bytes:
        self._events["blockDataAvailable"].wait()  # Wait until a block of data is available.
        self._bytesLock.acquire()
        try:
            readData = self._soundFile_read_and_fix(playbackBlockSize)
        except AssertionError as e:
            logging.debug("Exception in buffer_read (likely not enough data left), read what is available...")
            try:
                readData = self._soundFile_read_and_fix()
            except AssertionError as en:
                logging.debug("Mismatch in the number of frames read.")
                logging.debug("This only seems to be an issue when it happens with files that have ID3v2 tags.")
                logging.debug("Ignore it and return empty.")
                readData = b""

        logging.debug("Checking remaining bytes...")
        currentPos = self._bytesFile.tell()
        self._bytesFile.seek(0, os.SEEK_END)
        endPos = self._bytesFile.tell()
        logging.debug("Remaining file length: " + str(endPos - currentPos) + "\n")
        self._bytesFile.seek(currentPos)
        remainingBytes = endPos - currentPos

        if remainingBytes < playbackBlockSize and not self._events["downloadDoneEvent"].is_set():
            logging.debug("Marking no available blocks...")
            self._events["blockDataAvailable"].clear()  # Download isn't over and we've consumed enough data to where there isn't another block available.

        logging.debug("Read bytes: " + str(len(readData)) + "\n")

        self._bytesLock.release()
        return readData
    def play_preview(self, playInBackground:bool, portaudioDeviceID:Optional[int] = None) -> None:
        """
        Plays the preview audio.

        Args:
            playInBackground: A bool indicating whether to play the audio in the background.
            portaudioDeviceID: Optional int indicating the device ID to use for audio playback.

        Returns:
            None
        """
        # This will error out if the preview hasn't been generated
        play_audio_bytes(self.get_preview_bytes(), playInBackground, portaudioDeviceID)
        return

    def get_preview_bytes(self) -> bytes:
        """
        Returns the preview audio in bytes.

        Returns:
            bytes: The preview audio in bytes.

        Raises:
            RuntimeError: If no preview URL is available.
        """
        # This will error out if the preview hasn't been generated
        previewURL = self.get_preview_url()
        if previewURL is None:
            raise RuntimeError("No preview URL available!")
        response = requests.get(previewURL, allow_redirects=True)
        return response.content
    def get_settings(self) -> dict:
        """
        Get the name of the current voice.

        Returns:
            str: The name of the voice.
        """
        # We don't store the name OR the settings, as they can be changed externally.
        response = api_get("/voices/" + self._voiceID + "/settings", self._linkedUser.headers)
        return response.json()

    def get_name(self) -> str:
        """
        Get the name of the current voice.

        Returns:
            str: The name of the voice.
        """
        response = api_get("/voices/" + self._voiceID, self._linkedUser.headers)
        return response.json()["name"]

    def get_preview_url(self) -> str|None:
        """
        Get the preview URL of the current voice.

        Returns:
            str|None: The preview URL of the voice, or None if it doesn't exist.
        """
        response = api_get("/voices/" + self._voiceID, self._linkedUser.headers)
        return response.json()["preview_url"]

    def edit_settings(self, stability:float=None, similarity_boost:float=None):
        """
        Edit the settings of the current voice.

        Args:
            stability (float, optional): The stability of the voice. If None, the current stability setting will be used. Defaults to None.
            similarity_boost (float, optional): The similarity boost of the voice. If None, the current similarity boost setting will be used. Defaults to None.

        Raises:
            ValueError: If the provided stability or similarity_boost value is not between 0 and 1.
        """
        if stability is None or similarity_boost is None:
            oldSettings = self.get_settings()
            if stability is None: stability = oldSettings["stability"]
            if similarity_boost is None: stability = oldSettings["similarity_boost"]

        if not(0 <= stability <= 1 and 0 <= similarity_boost <= 1):
            raise ValueError("Please provide a value between 0 and 1.")
        payload = {"stability": stability, "similarity_boost": similarity_boost}
        api_json("/voices/" + self._voiceID + "/settings/edit", self._linkedUser.headers, jsonData=payload)

    @property
    def category(self):
        return self._category
    @property
    def labels(self):
        return self._labels

    # Since the same voice can be available for multiple users, we allow the user to change which API key is used.
    @property
    def linkedUser(self):
        """
        Returns the user currently linked to the voice, whose API key will be used.

        Returns:
            ElevenLabsUser: The user linked to the voice.

        """
        return self._linkedUser

    @linkedUser.setter
    def linkedUser(self, newUser: ElevenLabsUser):
        """
        Set the user linked to the voice, whose API key will be used.

        Args:
            newUser (ElevenLabsUser): The new user to link to the voice.

        Returns:
            None

        """
        self._linkedUser = newUser

    @property
    def voiceID(self):
        return self._voiceID


class ElevenLabsGeneratedVoice(ElevenLabsVoice):
    def __init__(self, voiceData, linkedUser: ElevenLabsUser):
        super().__init__(voiceData, linkedUser)

    def edit_voice(self, newName:str = None, newLabels:dict[str, str] = None):
        """
        Edit the name/labels of the voice.

        Args:
            newName (str): The new name for the voice.
            newLabels (str): The new labels for the voice.
        """
        if newName is None:
            newName = self.get_name()
        payload = {"name": newName}

        if newLabels is not None:
            if len(newLabels.keys()) > 5:
                raise ValueError("Too many labels! The maximum amount is 5.")
            payload["labels"] = newLabels
        api_multipart("/voices/" + self._voiceID + "/edit", self._linkedUser.headers, data=payload)
    def delete_voice(self):
        """
        This function deletes the current voice.

        Returns:
            None

        Raises:
            RuntimeError: If the voice is a premade voice.

        """
        if self._category == "premade":
            raise RuntimeError("Cannot delete premade voices!")
        response = api_del("/voices/"+self._voiceID, self._linkedUser.headers)
        self._voiceID = ""


class ElevenLabsClonedVoice(ElevenLabsVoice):
    def __init__(self, voiceData, linkedUser: ElevenLabsUser):
        super().__init__(voiceData, linkedUser)


    def get_samples(self) -> list[ElevenLabsSample]:
        response = api_get("/voices/" + self._voiceID, self._linkedUser.headers)
        outputList = list()
        samplesData = response.json()["samples"]
        from elevenlabslib.ElevenLabsSample import ElevenLabsSample
        for sampleData in samplesData:
            outputList.append(ElevenLabsSample(sampleData, self))
        return outputList

    def edit_voice(self, newName:str = None, newLabels:dict[str, str] = None):
        """
        Edit the name/labels of the voice.

        Args:
            newName (str): The new name for the voice.
            newLabels (str): The new labels for the voice.
        """
        if newName is None:
            newName = self.get_name()
        payload = {"name": newName}

        if newLabels is not None:
            if len(newLabels.keys()) > 5:
                raise ValueError("Too many labels! The maximum amount is 5.")
            payload["labels"] = newLabels
        api_multipart("/voices/" + self._voiceID + "/edit", self._linkedUser.headers, data=payload)

    def add_samples_by_path(self, samples:list[str]):
        """
        This function adds samples to the current voice by their file paths.

        Args:
            samples (list[str]): A list of file paths to the sample audio files.

        Returns:
            None

        Raises:
            ValueError: If no samples are provided.

        """
        sampleBytes = {}
        for samplePath in samples:
            if "\\" in samplePath:
                fileName = samplePath[samplePath.rindex("\\")+1:]
            else:
                fileName = samplePath
            sampleBytes[fileName] = open(samplePath, "rb").read()
        self.add_samples_bytes(sampleBytes)

    #Requires a dict of filenames and bytes
    def add_samples_bytes(self, samples:dict[str, bytes]):
        """
        This function adds samples to the current voice by their file names and bytes.

        Args:
            samples (dict[str, bytes]): A dictionary of sample audio file names and their respective bytes.

        Returns:
            None

        Raises:
            ValueError: If no samples are provided.

        """
        if len(samples.keys()) == 0:
            raise ValueError("Please add at least one sample!")

        payload = {"name":self.get_name()}
        files = list()
        for fileName, fileBytes in samples.items():
            files.append(("files", (fileName, io.BytesIO(fileBytes))))

        api_multipart("/voices/" + self._voiceID + "/edit", self._linkedUser.headers, data=payload, filesData=files)

    def delete_voice(self):
        """
        This function deletes the current voice.

        Returns:
            None

        Raises:
            RuntimeError: If the voice is a premade voice.

        """
        if self._category == "premade":
            raise RuntimeError("Cannot delete premade voices!")
        response = api_del("/voices/"+self._voiceID, self._linkedUser.headers)
        self._voiceID = ""