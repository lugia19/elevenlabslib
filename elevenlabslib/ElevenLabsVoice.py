from __future__ import annotations

import io
import os
import queue

import threading
from typing import BinaryIO, Optional

import soundfile as sf
import sounddevice as sd
import numpy

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from elevenlabslib.ElevenLabsSample import ElevenLabsSample

from elevenlabslib.ElevenLabsUser import ElevenLabsUser
from elevenlabslib.helpers import *

playbackBlockSize = 2048
downloadChunkSize = 4096
playbackBufferSizeInBlocks = 20


class ElevenLabsVoice:
    def __init__(self, voiceData, linkedUser:ElevenLabsUser):
        self._linkedUser = linkedUser
        # This is the name at the time the object was created. It won't be updated.
        # (Useful to iterate over all voices to find one with a specific name without spamming the API)
        self.initialName = voiceData["name"]
        self._voiceID = voiceData["voice_id"]
        self._category = voiceData["category"]

        self.q = queue.Queue(maxsize=playbackBufferSizeInBlocks)
        self.bytesFile = io.BytesIO()
        self.bytesSoundFile: Optional[sf.SoundFile] = None    #Needs to be created later.
        self.bytesLock = threading.Lock()
        self.playbackFinishedEvent = threading.Event()
        self.headerReadyEvent = threading.Event()
        self.soundFileReadyEvent = threading.Event()
        self.downloadDoneEvent = threading.Event()
        self.blockDataAvailable = threading.Event()

    def _generate_payload(self, prompt:str, stability:Optional[float]=None, similarity_boost:Optional[float]=None) -> dict:
        payload = {"text": prompt}
        if stability is not None or similarity_boost is not None:
            existingSettings = self.get_settings()
            if stability is None: stability = existingSettings["stability"]
            if similarity_boost is None: similarity_boost = existingSettings["similarity_boost"]
            if not (stability <= 1 and similarity_boost <= 1):
                raise ValueError("Please provide a value equal or below 1.")
            payload["voice_settings"] = dict()
            payload["voice_settings"]["stability"] = stability
            payload["voice_settings"]["similarity_boost"] = similarity_boost
        return payload

    def generate_audio_bytes(self, prompt:str, stability:Optional[float]=None, similarity_boost:Optional[float]=None) -> bytes:
        #The output from the site is an mp3 file.
        #You can check the README for an example of how to convert it to wav on the fly using pydub and bytesIO.
        payload = self._generate_payload(prompt, stability, similarity_boost)
        try:
            response = api_json("/text-to-speech/" + self._voiceID + "/stream", self._linkedUser.headers, jsonData=payload)
        except Exception as e:
            logging.exception(e)
            raise e

        return response.content



    # <editor-fold desc="Janktastic streaming nightmare.">
    #This uses a more advanced method to play back the audio more quickly. The audio can sometimes skip.
    #IT IS ALWAYS BLOCKING. If you don't want it to block, figure it out. Not my problem.
    def generate_and_stream_audio(self,prompt:str, portaudioDeviceID:Optional[int] = None, stability:Optional[float]=None, similarity_boost:Optional[float]=None):
        payload = self._generate_payload(prompt, stability, similarity_boost)
        path = "/text-to-speech/" + self._voiceID + "/stream"
        if portaudioDeviceID is None:
            portaudioDeviceID = sd.default.device

        downloadThread = threading.Thread(target=self._stream_downloader_function, args=(path, payload))
        downloadThread.start()

        while True:
            print("Waiting for header event...")
            self.headerReadyEvent.wait()
            print("Header maybe ready?")
            try:
                with self.bytesLock:
                    self.bytesSoundFile = sf.SoundFile(self.bytesFile)
                    print("File created (" + str(self.bytesFile.tell()) + " bytes read).")
                    self.soundFileReadyEvent.set()
                    break
            except sf.LibsndfileError:
                self.bytesFile.seek(0)
                dataBytes = self.bytesFile.read()
                self.bytesFile.seek(0)
                print("Error creating the soundfile with " + str(len(dataBytes)) + " bytes of data. Let's clear the headerReady event.")
                self.headerReadyEvent.clear()
                self.soundFileReadyEvent.set()

        stream = sd.RawOutputStream(
            samplerate=self.bytesSoundFile.samplerate, blocksize=playbackBlockSize,
            device=portaudioDeviceID, channels=self.bytesSoundFile.channels, dtype='float32',
            callback=self._stream_playback_callback, finished_callback=self.playbackFinishedEvent.set)
        print("Starting playback...")
        with stream:
            timeout = playbackBlockSize * playbackBufferSizeInBlocks / self.bytesSoundFile.samplerate
            # data = getDataFromDownload(bytesSoundFile)
            while True:
                data = self._insert_into_queue_from_download_thread()
                if data != b"":
                    print("Putting " + str(len(data)) + " bytes in queue.")
                    self.q.put(data, timeout=timeout)
                else:
                    print("Got back no data, let's not write that to the queue...")
                    with self.bytesLock:
                        oldPos = self.bytesFile.tell()
                        endPos = self.bytesFile.seek(0, os.SEEK_END)
                        self.bytesFile.seek(oldPos)
                        if endPos == oldPos and self.downloadDoneEvent.is_set():
                            break
            print("While loop done.")
            self.playbackFinishedEvent.wait()  # Wait until playback is finished
            print(stream.active)
        print("Stream done.")

        return

    def _stream_downloader_function(self, path, payload):
        # This is the function running in the download thread.
        streamedRequest = requests.post(api_endpoint + path, headers=self._linkedUser.headers, json=payload, stream=True)

        streamedRequest.raise_for_status()
        totalLength = 0
        print("Starting iter...")
        for chunk in streamedRequest.iter_content(chunk_size=downloadChunkSize):
            if self.headerReadyEvent.is_set():
                print("HeaderReady is set, waiting for the soundfile...")
                self.soundFileReadyEvent.wait()  # Wait for the soundfile to be created.
                if not self.headerReadyEvent.is_set():
                    print("headerReady was cleared by the playback thread. Header data still missing, download more.")
                    self.soundFileReadyEvent.clear()

            totalLength += len(chunk)
            if len(chunk) != downloadChunkSize:
                print("Writing weirdly sized chunk (" + str(len(chunk)) + ")...")

            # Write the new data then seek back to the initial position.
            with self.bytesLock:
                if not self.headerReadyEvent.is_set():
                    print("headerReady not set, setting it...")
                    self.bytesFile.seek(0, os.SEEK_END)  # MAKE SURE the head is at the end.
                    self.bytesFile.write(chunk)
                    self.bytesFile.seek(0)  # Move the head back.
                    self.headerReadyEvent.set()  # We've never downloaded a single chunk before. Do that and move the head back, then fire the event.
                else:
                    lastReadPos = self.bytesFile.tell()
                    lastWritePos = self.bytesFile.seek(0, os.SEEK_END)
                    self.bytesFile.write(chunk)
                    endPos = self.bytesFile.tell()
                    self.bytesFile.seek(lastReadPos)
                    print("Write head move: " + str(endPos - lastWritePos))
                    if endPos - lastReadPos > playbackBlockSize:  # We've read enough data to fill up a block, alert the other thread.
                        print("Raise available data event - " + str(endPos - lastReadPos) + " bytes available")
                        self.blockDataAvailable.set()

        print("Download finished - " + str(totalLength) + ".")
        self.downloadDoneEvent.set()
        self.blockDataAvailable.set()  # Ensure that the other thread knows data is available
        return

    def _stream_playback_callback(self, outdata, frames, timeData, status):
        assert frames == playbackBlockSize
        if status.output_underflow:
            logging.error('Output underflow: increase blocksize?')
            raise sd.CallbackAbort
        assert not status

        while True:
            try:
                readData = self.q.get_nowait()
                if len(readData) == 0 and not self.downloadDoneEvent.is_set():
                    print("An empty item got into the queue. Skip it.")
                    continue
                break
            except queue.Empty as e:
                if self.downloadDoneEvent.is_set():
                    print("Download (and playback) finished.")  # We're done.
                    raise sd.CallbackStop
                else:
                    # This should NEVER happen, as the getdownloaddata function handles waiting for new data to come in. ABORT.
                    print("Missing data but download isn't over. What the fuck?")
                    raise sd.CallbackAbort

        # Last read chunk was smaller than it should've been. It's either EOF or that stupid soundFile bug.
        if 0 < len(readData) < len(outdata):
            print("Data read smaller than it should've been.")
            print("Read " + str(len(readData)) + " bytes but expected " + str(len(outdata)) + ", padding...")

            # I still don't really understand why this happens - seems to be related to the soundfile bug.
            # Padding it like this means there ends up being a small portion of silence during the playback.

            outdata[:len(readData)] = readData
            outdata[len(readData):] = b'\x00' * (len(outdata) - len(readData))
        elif len(readData) == 0:
            print("Callback got no data from the queue. Checking if playback is over...")
            with self.bytesLock:
                oldPos = self.bytesFile.tell()
                endPos = self.bytesFile.seek(0, os.SEEK_END)
                if oldPos == endPos and self.downloadDoneEvent.is_set():
                    print("EOF reached and download over! Stopping callback...")
                    raise sd.CallbackStop
                else:
                    print("...Read no data but the download isn't over, what the fuck? Panic. Just send silence.")
                    outdata[len(readData):] = b'\x00' * (len(outdata) - len(readData))
        else:
            outdata[:] = readData
    #THIS FUNCTION ASSUMES YOU'VE GIVEN THE THREAD THE LOCK.
    def _soundFile_read_and_fix(self, dataToRead:int=-1, dtype="float32"):
        readData = self.bytesSoundFile.buffer_read(dataToRead, dtype=dtype)
        if len(readData) == 0:
            print("No data read.")
            print("Frame counter must be outdated, recreating soundfile...")
            self.bytesFile.seek(0)
            newSF = sf.SoundFile(self.bytesFile)
            newSF.seek(self.bytesSoundFile.tell())
            self.bytesSoundFile = newSF
            readData = self.bytesSoundFile.buffer_read(dataToRead, dtype=dtype)
            print("Now read " + str(len(readData)) + " bytes. I sure fucking hope that number isn't zero.")
        return readData
    def _insert_into_queue_from_download_thread(self) -> bytes:
        self.blockDataAvailable.wait()  # Wait until a block of data is available.
        self.bytesLock.acquire()
        try:
            readData = self._soundFile_read_and_fix(playbackBlockSize)
        except AssertionError as e:
            print("Exception in buffer_read (likely not enough data left), read what is available...")
            try:
                readData = self._soundFile_read_and_fix()
            except AssertionError as en:
                print("Mismatch in the number of frames read.")
                print("This only seems to be an issue when it happens with files that have ID3v2 tags.")
                print("Ignore it and return empty.")
                readData = b""

        print("Checking remaining bytes...")
        currentPos = self.bytesFile.tell()
        self.bytesFile.seek(0, os.SEEK_END)
        endPos = self.bytesFile.tell()
        print("Remaining file length: " + str(endPos - currentPos) + "\n")
        self.bytesFile.seek(currentPos)
        remainingBytes = endPos - currentPos

        if remainingBytes < playbackBlockSize and not self.downloadDoneEvent.is_set():
            print("Marking no available blocks...")
            self.blockDataAvailable.clear()  # Download isn't over and we've consumed enough data to where there isn't another block available.

        print("Read bytes: " + str(len(readData)) + "\n")

        self.bytesLock.release()
        return readData
    # </editor-fold>

    def generate_and_play_audio(self, prompt:str, playInBackground:bool, portaudioDeviceID:Optional[int] = None, stability:Optional[float]=None, similarity_boost:Optional[float]=None) -> None:
        play_audio_bytes(self.generate_audio_bytes(prompt, stability, similarity_boost), playInBackground, portaudioDeviceID)
        return

    def get_samples(self) -> list[ElevenLabsSample]:
        response = api_get("/voices/" + self._voiceID, self._linkedUser.headers)
        outputList = list()
        samplesData = response.json()["samples"]
        from elevenlabslib.ElevenLabsSample import ElevenLabsSample
        for sampleData in samplesData:
            outputList.append(ElevenLabsSample(sampleData, self))
        return outputList

    #This will error out if the preview hasn't been generated
    def play_preview(self, playInBackground:bool, portaudioDeviceID:Optional[int] = None) -> None:
        play_audio_bytes(self.get_preview_bytes(), playInBackground, portaudioDeviceID)
        return

    def get_preview_bytes(self) -> bytes:
        previewURL = self.get_preview_url()
        if previewURL is None:
            raise Exception("No preview URL available!")
        response = requests.get(previewURL, allow_redirects=True)
        return response.content


    def get_settings(self) -> dict:
        # We don't store the name OR the settings, as they can be changed externally.
        response = api_get("/voices/" + self._voiceID + "/settings", self._linkedUser.headers)
        return response.json()

    def get_name(self) -> str:
        response = api_get("/voices/" + self._voiceID, self._linkedUser.headers)
        return response.json()["name"]

    def get_preview_url(self) -> str|None:
        response = api_get("/voices/" + self._voiceID, self._linkedUser.headers)
        return response.json()["preview_url"]

    def edit_settings(self, stability:float=None, similarity_boost:float=None):
        if stability is None or similarity_boost is None:
            oldSettings = self.get_settings()
            if stability is None: stability = oldSettings["stability"]
            if similarity_boost is None: stability = oldSettings["similarity_boost"]

        if not(stability <= 1 and similarity_boost <= 1):
            raise ValueError("Please input a value that is less than or equal to 1.")
        payload = {"stability": stability, "similarity_boost": similarity_boost}
        api_json("/voices/" + self._voiceID + "/settings/edit", self._linkedUser.headers, jsonData=payload)

    def edit_name(self, newName:str):
        payload = {"name":newName}
        api_multipart("/voices/" + self._voiceID + "/edit", self._linkedUser.headers, data=payload)

    def add_samples_by_path(self, samples:list[str]):
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
        if len(samples.keys()) == 0:
            raise Exception("Please add at least one sample!")

        payload = {"name":self.get_name()}
        files = list()
        for fileName, fileBytes in samples.items():
            files.append(("files", (fileName, io.BytesIO(fileBytes))))

        api_multipart("/voices/" + self._voiceID + "/edit", self._linkedUser.headers, data=payload, filesData=files)

    def delete_voice(self):
        if self._category == "premade":
            raise Exception("Cannot delete premade voices!")
        response = api_del("/voices/"+self._voiceID, self._linkedUser.headers)
        self._voiceID = ""

    @property
    def category(self):
        return self._category

    # Since the same voice can be available for multiple users, we allow the user to change which API key is used.
    @property
    def linkedUser(self):
        return self._linkedUser

    @linkedUser.setter
    def linkedUser(self, newUser: ElevenLabsUser):
        self._linkedUser = newUser

    @property
    def voiceID(self):
        return self._voiceID