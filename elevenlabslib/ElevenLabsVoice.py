from __future__ import annotations

import audioop
import base64
import concurrent.futures
import inspect
import math
from concurrent.futures import Future
from typing import Iterator, AsyncIterator
from typing import TYPE_CHECKING

import numpy
import numpy as np
import websockets
from websockets.sync.client import connect

if TYPE_CHECKING:
    from elevenlabslib.ElevenLabsSample import ElevenLabsSample
    from elevenlabslib.ElevenLabsUser import ElevenLabsUser

from elevenlabslib.helpers import *
from elevenlabslib.helpers import _api_json, _api_del, _api_get, _api_multipart, _api_tts_with_concurrency, _text_chunker

# These are hardcoded because they just plain work. If you really want to change them, please be careful.
_playbackBlockSize = 2048
_downloadChunkSize = 4096
class ElevenLabsVoice:
    """
    Represents a voice in the ElevenLabs API.

    It's the parent class for all voices, and used directly for the premade ones.
    """
    @staticmethod
    def edit_stream_settings(playbackBlockSize=None, downloadChunkSize=None) -> None:
        """
        This function lets you override the default values used for the streaming function.

        Danger:
            This change affects all voices.

            Please only do this if you know what you're doing.

        Parameters:
            playbackBlockSize (int): The size (in frames) of the blocks used for playback.
            downloadChunkSize (int): The size (in bytes) of the chunks to be downloaded.
        """
        global _playbackBlockSize, _downloadChunkSize
        if playbackBlockSize is not None:
            _playbackBlockSize = playbackBlockSize
        if downloadChunkSize is not None:
            _downloadChunkSize = downloadChunkSize

    @staticmethod
    def voiceFactory(voiceData, linkedUser: ElevenLabsUser) -> ElevenLabsVoice | ElevenLabsEditableVoice | ElevenLabsClonedVoice | ElevenLabsProfessionalVoice:
        """
        Initializes a new instance of ElevenLabsVoice or one of its subclasses depending on voiceData.

        Args:
            voiceData: A dictionary containing the voice data.
            linkedUser: An instance of the ElevenLabsUser class representing the linked user.

        Returns:
            ElevenLabsVoice | ElevenLabsDesignedVoice | ElevenLabsClonedVoice: The voice object
        """
        category = voiceData["category"]
        if category == "premade":
            return ElevenLabsVoice(voiceData, linkedUser)
        elif category == "cloned":
            return ElevenLabsClonedVoice(voiceData, linkedUser)
        elif category == "generated":
            return ElevenLabsDesignedVoice(voiceData, linkedUser)
        elif category == "professional":
            return ElevenLabsProfessionalVoice(voiceData, linkedUser)
        else:
            raise ValueError(f"{category} is not a valid voice category!")

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
        self._name = voiceData["name"]
        self._description = voiceData["description"]
        self._voiceID = voiceData["voice_id"]
        self._category = voiceData["category"]
        self._sharingData = voiceData["sharing"]
        self._settings = voiceData["settings"]

    def get_settings(self) -> dict:
        warn("The new method is to use the properties combined with update_data(). See the guide at https://elevenlabslib.readthedocs.io.", DeprecationWarning)

        return self.update_data()["settings"]

    def update_data(self) -> dict:
        """
        Tip:
            I've only added specific getters for the most common attributes (name/description).

            Use this function for all other metadata.

            Additionally, this also updates all the properties of the voice (name, description, etc).

        Returns:
            dict: A dict containing all the metadata for the voice, such as the name, the description, etc.
        """
        response = _api_get("/voices/" + self._voiceID, self._linkedUser.headers, params={"with_settings": True})

        voiceData = response.json()
        self._name = voiceData["name"]
        self._description = voiceData["description"]
        self._sharingData = voiceData["sharing"]
        self._settings = voiceData["settings"]

        return response.json()

    def get_info(self) -> dict:
        warn("Deprecated. voice.update_data() fulfills the same role.", DeprecationWarning)
        return self.update_data()


    def get_name(self) -> str:
        warn("Deprecated. The new method is to use the properties combined with update_data(). See the guide at https://elevenlabslib.readthedocs.io.", DeprecationWarning)
        return self.update_data()["name"]

    def get_description(self) -> str|None:
        warn("Deprecated. The new method is to use the properties combined with update_data(). See the guide at https://elevenlabslib.readthedocs.io.", DeprecationWarning)
        return self.update_data()["description"]

    @property
    def category(self):
        """
        This property indicates the "type" of the voice, whether it's premade, cloned, designed etc.
        """
        return self._category

    @property
    def linkedUser(self):
        """
        Note:
            This property can also be set.
            This is mostly in case some future update adds shared voices (beyond the currently available premade ones).

        The user currently linked to the voice, whose API key will be used to generate audio.

        Returns:
            ElevenLabsUser: The user linked to the voice.

        """
        return self._linkedUser

    @linkedUser.setter
    def linkedUser(self, newUser: ElevenLabsUser):
        """
        Set the user linked to the voice, whose API key will be used.

        Warning:
            Only supported for premade voices, as others do not have consistent IDs.

        Args:
            newUser (ElevenLabsUser): The new user to link to the voice.

        """
        if self.category != "premade":
            raise ValueError("Cannot change linked user of a non-premade voice.")
        self._linkedUser = newUser

    @property
    def voiceID(self):
        return self._voiceID

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return self._description

    @property
    def settings(self):
        if self._settings is None:
            self.update_data()

        return self._settings

    def edit_settings(self, stability:float=None, similarity_boost:float=None, style:float=None, use_speaker_boost:bool=None):
        """
        Note:
            If either argument is omitted, the current values will be used instead.

        Edit the settings of the current voice.

        Args:
            stability (float, optional): The stability to set.
            similarity_boost (float, optional): The similarity boost to set.
            style (float, optional): The style to set (v2 models only).
            use_speaker_boost (bool, optional): Whether to enable the speaker boost (v2 models only).

        Raises:
            ValueError: If the provided values don't fit the correct ranges.
        """

        if None in (stability, similarity_boost, style, use_speaker_boost):
            oldSettings = self.settings
            if stability is None: stability = oldSettings["stability"]
            if similarity_boost is None: stability = oldSettings["similarity_boost"]
            if style is None: style = oldSettings["style"]
            if use_speaker_boost is None: style = oldSettings["use_speaker_boost"]

        for arg in (stability, similarity_boost, style):
            if not (0 <= arg <= 1):
                raise ValueError("Please provide a value between 0 and 1.")
        payload = {"stability": stability, "similarity_boost": similarity_boost, "style":style, "use_speaker_boost":use_speaker_boost}
        _api_json("/voices/" + self._voiceID + "/settings/edit", self._linkedUser.headers, jsonData=payload)
        self._settings = payload

    def _generate_payload(self, prompt:Union[str, bytes, BinaryIO], generationOptions:GenerationOptions=None):
        """
        Generates the payload for the text-to-speech API call.

        Args:
            prompt (str|bytes): The prompt or audio to generate speech for.
            generationOptions (GenerationOptions): The options for this generation.
        Returns:
            dict: A dictionary representing the payload for the API call.
        """
        if generationOptions is None:
            generationOptions = GenerationOptions()

        overriddenVoiceSettings = [generationOptions.stability, generationOptions.similarity_boost]
        if "v2" in generationOptions.model_id:
            overriddenVoiceSettings.append(generationOptions.style)
            overriddenVoiceSettings.append(generationOptions.use_speaker_boost)

        include_settings = False
        voice_settings = None
        for value in overriddenVoiceSettings:
            if value is not None:
                include_settings = True
                break

        if include_settings:
            currentSettings = self.settings
            voice_settings = dict()
            for key, currentValue in currentSettings.items():
                overriddenValue = getattr(generationOptions, key, None)
                voice_settings[key] = overriddenValue if overriddenValue is not None else currentValue

        model_id = generationOptions.model_id

        if isinstance(prompt, str):
            payload = {
                "model_id": model_id,
                "text": apply_pronunciations(prompt, generationOptions)
            }
        else:
            payload = {"model_id": model_id}

        if voice_settings is not None:
            if isinstance(prompt, str):
                payload["voice_settings"] = voice_settings
            else:
                payload["voice_settings"] = json.dumps(voice_settings)

        return payload

    def _generate_parameters(self, generationOptions:GenerationOptions = None):
        if generationOptions is None:
            generationOptions = GenerationOptions()
        params = dict()
        generationOptions = self.linkedUser.get_real_audio_format(generationOptions)
        params["optimize_streaming_latency"] = generationOptions.latencyOptimizationLevel
        params["output_format"] = generationOptions.output_format
        return params

    def _generate_websocket_connection(self, generationOptions:GenerationOptions=None, websocketOptions:WebsocketOptions=None) -> websockets.sync.client.ClientConnection:
        """
        Generates a websocket connection for the input-streaming endpoint.

        Args:
            generationOptions (GenerationOptions): The options for this generation.
        Returns:
            dict: A dictionary representing the payload for the API call.
        """
        voice_settings = None
        if generationOptions is None:
            generationOptions = GenerationOptions()

        overriddenVoiceSettings = [generationOptions.stability, generationOptions.similarity_boost]
        if "v2" in generationOptions.model_id:
            overriddenVoiceSettings.append(generationOptions.style)
            overriddenVoiceSettings.append(generationOptions.use_speaker_boost)

        if None in overriddenVoiceSettings:
            # The user overrode some voice settings, but not all of them. Let's fetch the others.
            currentSettings = self.settings
            voice_settings = dict()
            for key, currentValue in currentSettings.items():
                overriddenValue = getattr(generationOptions, key, None)
                voice_settings[key] = overriddenValue if overriddenValue is not None else currentValue

        if websocketOptions is None:
            websocketOptions = WebsocketOptions()
        BOS = {
            "text": " ",
            "try_trigger_generation": websocketOptions.try_trigger_generation,
            "generation_config": {
                "chunk_length_schedule": websocketOptions.chunk_length_schedule
            }
        }

        if voice_settings is not None:
            BOS["voice_settings"] = voice_settings
        websocketURL = f"wss://api.elevenlabs.io/v1/text-to-speech/{self.voiceID}/stream-input?model_id={generationOptions.model_id}"
        for key, value in self._generate_parameters(generationOptions).items():
            websocketURL += f"&{key}={value}"
        websocketURL += f"&enable_ssml_parsing={str(websocketOptions.enable_ssml_parsing).lower()}"
        websocket = connect(
            websocketURL,
            additional_headers=self.linkedUser.headers
        )
        websocket.send(json.dumps(BOS))

        return websocket

    def generate_to_historyID_v2(self, prompt: Union[str,bytes,BinaryIO], generationOptions:GenerationOptions=None) -> str:
        """
        Generate audio bytes from the given prompt and returns the historyItemID corresponding to it.

        Parameters:
            prompt (str, bytes, BinaryIO): The text prompt or audio bytes/file pointer to generate audio from.
            generationOptions (GenerationOptions): Options for the audio generation such as the model to use and the voice settings.
        Returns:
            The ID for the new HistoryItem
        """
        if generationOptions is None:
            generationOptions = GenerationOptions()

        payload = self._generate_payload(prompt, generationOptions)
        params = self._generate_parameters(generationOptions)

        if not isinstance(prompt, str):
            if "output_format" in params:
                params.pop("output_format")
            source_audio, prompt = io_hash_from_audio(prompt)

            files = {"audio": source_audio}

            requestFunction = lambda: _api_multipart("/speech-to-speech/" + self._voiceID + "/stream", self._linkedUser.headers, data=payload, params=params, filesData=files)
        else:
            requestFunction = lambda: _api_json("/text-to-speech/" + self._voiceID + "/stream", self._linkedUser.headers, jsonData=payload, stream=True, params=params)


        generationID = f"{self.voiceID} - {prompt} - {time.time()}"
        response = _api_tts_with_concurrency(requestFunction, generationID, self._linkedUser.generation_queue)

        if "history-item-id" in response.headers:
            history_id = response.headers["history-item-id"]
        else:
            history_id = "no_history_id_available"
        return history_id

    def _generate_audio_prompting(self, prompt:str, generationOptions:GenerationOptions, promptingOptions:PromptingOptions):
        """
        Internal use only, just wraps stream_audio_no_playback.
        """
        audio_queue, transcript_queue = self.stream_audio_no_playback(prompt, generationOptions, promptingOptions=promptingOptions)

        audio_chunk: numpy.ndarray = audio_queue.get()
        shape_of_chunk = audio_chunk.shape
        empty_shape = (0,) + shape_of_chunk[1:]
        all_audio = np.empty(empty_shape, dtype=audio_chunk.dtype)
        while audio_chunk is not None:
            all_audio = np.concatenate((all_audio, audio_chunk), axis=0)
            audio_chunk = audio_queue.get()
        final_audio = io.BytesIO()

        audio_extension = ""
        if "mp3" in generationOptions.output_format: audio_extension = "mp3"
        if "pcm" in generationOptions.output_format: audio_extension = "wav"
        if "ulaw" in generationOptions.output_format: audio_extension = "wav"
        save_audio_v2(all_audio, final_audio, audio_extension)
        final_audio.seek(0)
        audioData = final_audio.read()
        return audioData

    def generate_audio_v2(self, prompt: Union[str,bytes, BinaryIO], generationOptions:GenerationOptions=GenerationOptions(), promptingOptions:PromptingOptions=None) -> tuple[bytes,str]:
        """
        Generates speech for the given prompt or audio and returns the audio data as bytes of an mp3 file alongside the new historyID.

        Tip:
            If you would like to save the audio to disk or otherwise, you can use helpers.save_audio_bytes().

        Args:
            prompt (str|bytes|BinaryIO): The text prompt or audio bytes/file pointer to generate speech for.
            generationOptions (GenerationOptions): Options for the audio generation such as the model to use and the voice settings.
            promptingOptions (PromptingOptions): Options for pre/post prompting the audio, for improved emotion. Ignored for speech to speech.
        Returns:
            A tuple consisting of the bytes of the audio file and its historyID.

        Note:
            If using PCM as the output_format, the return audio bytes are a WAV.
        """

        #Since we need the sample rate directly, make sure it's a real one.
        generationOptions = self.linkedUser.get_real_audio_format(generationOptions)

        payload = self._generate_payload(prompt, generationOptions)
        params = self._generate_parameters(generationOptions)
        if isinstance(prompt, str):
            requestFunction = lambda: _api_json("/text-to-speech/" + self._voiceID + "/stream", self._linkedUser.headers, jsonData=payload, params=params)
        else:
            if "output_format" in params:
                params.pop("output_format")

            source_audio, prompt = io_hash_from_audio(prompt)
            files = {"audio": source_audio}

            requestFunction = lambda: _api_multipart("/speech-to-speech/" + self._voiceID + "/stream", self._linkedUser.headers, data=payload, params=params, filesData=files)

        if isinstance(prompt,str) and promptingOptions is not None:
            audioData = self._generate_audio_prompting(prompt, generationOptions, promptingOptions)
            history_id = "no_history_id_available"
        else:
            generationID = f"{self.voiceID} - {prompt} - {time.time()}"
            responseConnection = _api_tts_with_concurrency(requestFunction, generationID, self._linkedUser.generation_queue)
            audioData = responseConnection.content

            if "output_format" in params:
                if "pcm" in params["output_format"]:
                    audioData = pcm_to_wav(audioData, int(params["output_format"].lower().replace("pcm_", "")))
                if "ulaw" in params["output_format"]:
                    audioData = ulaw_to_wav(audioData, int(params["output_format"].lower().replace("ulaw_", "")))

            if "history-item-id" in responseConnection.headers:
                history_id = responseConnection.headers["history-item-id"]
            else:
                history_id = "no_history_id_available"

        return audioData, history_id

    def generate_play_audio_v2(self, prompt:Union[str,bytes, BinaryIO], playbackOptions:PlaybackOptions=PlaybackOptions(), generationOptions:GenerationOptions=GenerationOptions(), promptingOptions:PromptingOptions=None) -> tuple[bytes,str, sd.OutputStream]:
        """
        Generate audio bytes from the given prompt and play them using sounddevice.

        Tip:
            This function downloads the entire file before playing it back, and even if playInBackground is set, it will halt execution until the file is downloaded.
            If you need faster response times and background downloading and playback, use generate_and_stream_audio_v2.

        Parameters:
            prompt (str|bytes|BinaryIO): The text prompt or audio bytes/file pointer to generate audio from.
            playbackOptions (PlaybackOptions, optional): Options for the audio playback such as the device to use and whether to run in the background.
            generationOptions (GenerationOptions, optional): Options for the audio generation such as the model to use and the voice settings.
            promptingOptions (PromptingOptions): Options for pre/post prompting the audio, for improved emotion. Ignored for speech to speech.

        Returns:
           A tuple consisting of the bytes of the audio file, its historyID and the sounddevice OutputStream, to allow you to pause/stop the playback early.

        Note:
            If using PCM as the output_format, the return audio bytes are a WAV.
        """
        if generationOptions is None:
            generationOptions = GenerationOptions()

        audioData, historyID = self.generate_audio_v2(prompt, generationOptions, promptingOptions)
        outputStream = play_audio_v2(audioData, playbackOptions, self._linkedUser.get_real_audio_format(generationOptions).output_format)

        return audioData, historyID, outputStream

    def generate_stream_audio_v2(self, prompt:Union[str, Iterator[str], AsyncIterator, bytes, BinaryIO],
                                 playbackOptions:PlaybackOptions=PlaybackOptions(),
                                 generationOptions:GenerationOptions=GenerationOptions(),
                                 websocketOptions:WebsocketOptions=WebsocketOptions(),
                                 promptingOptions:PromptingOptions=None) -> tuple[str, Future[Any], Optional[queue.Queue]]:
        """
        Generate audio bytes from the given prompt (or str iterator) and stream them using sounddevice.

        If the runInBackground option in PlaybackOptions is true, it will download the audio data in a separate thread, without pausing the main thread.

        Warning:
            Currently, when doing input streaming, the API does not return the history item ID. This function will therefore return None in those cases. I will fix it once it does.

        Parameters:
            prompt (str|Iterator[str]|bytes|BinaryIO): The text prompt to generate audio from OR an iterator that returns multiple strings (for input streaming) OR the bytes/file pointer of an audio file.
            playbackOptions (PlaybackOptions, optional): Options for the audio playback such as the device to use and whether to run in the background.
            generationOptions (GenerationOptions, optional): Options for the audio generation such as the model to use and the voice settings.
            websocketOptions (WebsocketOptions, optional): Options for the websocket streaming. Ignored if not passed when not using websockets.
            promptingOptions (PromptingOptions, optional): Options for pre/post prompting the audio, for improved emotion. Ignored for input streaming and STS.
        Returns:
            A tuple consisting of:
            -HistoryID for the newly created item
            -Future which will hold the audio OutputStream (to control playback)
            -Queue for transcripts, with None as the termination indicator.
        """

        is_sts = False  #This is just a bodge.

        #We need the real sample rate.
        generationOptions = self.linkedUser.get_real_audio_format(generationOptions)

        if isinstance(prompt, str) and promptingOptions is not None:
            old_prompt = prompt
            def write():
                for _ in range(1):
                    yield f'{promptingOptions.pre_prompt} "{old_prompt}" {promptingOptions.post_prompt}'
            prompt = write()
            websocketOptions = WebsocketOptions(try_trigger_generation=False, chunk_length_schedule=[500])
        else:
            promptingOptions = None     #Ignore them if not generating a normal string.

        if isinstance(prompt, str) and promptingOptions is None:
            payload = self._generate_payload(prompt, generationOptions)
            path = "/text-to-speech/" + self._voiceID + "/stream"
            #Not using input streaming
            params = self._generate_parameters(generationOptions)
            requestFunction = lambda: requests.post(api_endpoint + path, headers=self._linkedUser.headers, json=payload, stream=True,
                                                    params = params, timeout=requests_timeout)
            generationID = f"{self.voiceID} - {prompt} - {time.time()}"
            responseConnection = _api_tts_with_concurrency(requestFunction, generationID, self._linkedUser.generation_queue)
        elif isinstance(prompt, io.IOBase) or isinstance(prompt, bytes):
            is_sts = True
            payload = self._generate_payload(prompt, generationOptions)
            path = "/speech-to-speech/" + self._voiceID + "/stream"
            # Using speech to speech
            params = self._generate_parameters(generationOptions)
            if "output_format" in params:
                params.pop("output_format")

            source_audio, prompt = io_hash_from_audio(prompt)

            files = {"audio": source_audio}
            requestFunction = lambda: requests.post(api_endpoint + path, headers=self._linkedUser.headers, data=payload, stream=True,
                                                    params=params, timeout=requests_timeout, files=files)
            generationID = f"{self.voiceID} - {prompt} - {time.time()}"
            responseConnection = _api_tts_with_concurrency(requestFunction, generationID, self._linkedUser.generation_queue)
        elif isinstance(prompt, Iterator) or inspect.isasyncgen(prompt) or promptingOptions is not None:
            if inspect.isasyncgen(prompt):
                prompt = SyncIterator(prompt)
            responseConnection = self._generate_websocket_connection(generationOptions, websocketOptions)
        else:
            raise ValueError("Unknown type passed for prompt.")

        streamer:Union[_Mp3Streamer, _RAWStreamer]

        if "mp3" in generationOptions.output_format or is_sts:
            streamer = _Mp3Streamer(playbackOptions, responseConnection, generationOptions, websocketOptions, prompt, promptingOptions)
        else:
            streamer = _RAWStreamer(playbackOptions, responseConnection, generationOptions, websocketOptions, prompt, promptingOptions)

        audioStreamFuture = concurrent.futures.Future()

        if playbackOptions.runInBackground:
            mainThread = threading.Thread(target=streamer.begin_streaming, args=(audioStreamFuture,))
            mainThread.start()
        else:
            streamer.begin_streaming(audioStreamFuture)
        history_id = "no_history_id_available"
        transcript_queue = None
        if isinstance(responseConnection, requests.Response) and "history-item-id" in responseConnection.headers:
            history_id = responseConnection.headers["history-item-id"]

        if isinstance(responseConnection, websockets.sync.client.ClientConnection):
            transcript_queue = streamer.transcript_queue


        return history_id, audioStreamFuture, transcript_queue

    def stream_audio_no_playback(self, prompt:Union[str, Iterator[str], bytes, BinaryIO],
                                 generationOptions:GenerationOptions=GenerationOptions(), websocketOptions:WebsocketOptions=WebsocketOptions(),
                                 promptingOptions:PromptingOptions=None) -> (queue.Queue[numpy.ndarray], Optional[queue.Queue[str]]):
        """
        Generate audio bytes from the given prompt (or str iterator, with input streaming) and returns the data in a queue, without playback.

        If the runInBackground option in PlaybackOptions is true, it will download the audio data in a separate thread, without pausing the main thread.

        Parameters:
            prompt (str|Iterator[str]): The text prompt or audio bytes/file pointer to generate audio from OR an iterator that returns multiple strings (for input streaming).
            generationOptions (GenerationOptions, optional): Options for the audio generation such as the model to use and the voice settings.
            websocketOptions (WebsocketOptions, optional): Options for the websocket streaming. Ignored if not passed when not using websockets.
            promptingOptions (PromptingOptions, optional): Options for pre/post prompting the audio, for improved emotion. Ignored for input streaming and STS.
        Returns:
            A tuple consisting of:
            - Queue for the audio as float32 numpy arrays, with None acting as the termination indicator.
            - Queue for transcripts, with None as the termination indicator (if websocket streaming was used).
        """

        #We need the real sample rate.
        generationOptions = self.linkedUser.get_real_audio_format(generationOptions)

        if isinstance(prompt, str) and promptingOptions is not None:
            original_prompt = prompt
            def write():
                for _ in range(1):
                    yield f'{promptingOptions.pre_prompt} "{original_prompt}" {promptingOptions.post_prompt}'
            prompt = write()
            websocketOptions = WebsocketOptions(try_trigger_generation=False, chunk_length_schedule=[500])
        else:
            promptingOptions = None     #Ignore them if not generating a normal string.

        if isinstance(prompt, str):
            payload = self._generate_payload(prompt, generationOptions)
            path = "/text-to-speech/" + self._voiceID + "/stream"
            #Not using input streaming
            params = self._generate_parameters(generationOptions)
            requestFunction = lambda: requests.post(api_endpoint + path, headers=self._linkedUser.headers, json=payload, stream=True,
                                                    params = params, timeout=requests_timeout)
            generationID = f"{self.voiceID} - {prompt} - {time.time()}"
            responseConnection = _api_tts_with_concurrency(requestFunction, generationID, self._linkedUser.generation_queue)
        elif isinstance(prompt, io.IOBase) or isinstance(prompt, bytes):
            payload = self._generate_payload(prompt, generationOptions)
            path = "/speech-to-speech/" + self._voiceID + "/stream"
            # Using speech to speech
            params = self._generate_parameters(generationOptions)
            if "output_format" in params:
                params.pop("output_format")

            source_audio, prompt = io_hash_from_audio(prompt)
            files = {"audio": source_audio}

            requestFunction = lambda: requests.post(api_endpoint + path, headers=self._linkedUser.headers, data=payload, stream=True,
                                                    params=params, timeout=requests_timeout, files=files)
            generationID = f"{self.voiceID} - {prompt} - {time.time()}"
            responseConnection = _api_tts_with_concurrency(requestFunction, generationID, self._linkedUser.generation_queue)
        elif isinstance(prompt, Iterator) or inspect.isasyncgen(prompt):
            if inspect.isasyncgen(prompt):
                prompt = SyncIterator(prompt)
            responseConnection = self._generate_websocket_connection(generationOptions, websocketOptions)
        else:
            raise ValueError("Prompt is of unknown type.")

        streamer:_NumpyStreamer = _NumpyStreamer(responseConnection, generationOptions, websocketOptions, prompt, promptingOptions)
        mainThread = threading.Thread(target=streamer.begin_streaming)
        mainThread.start()

        if isinstance(responseConnection, requests.Response):
            return streamer.destination_queue, None
        else:
            return streamer.destination_queue, streamer.transcript_queue

    def get_preview_url(self) -> str|None:
        """
        Returns:
            str|None: The preview URL of the voice, or None if it hasn't been generated.
        """
        return self.update_data()["preview_url"]

    def get_preview_bytes(self) -> bytes:
        """
        Returns:
            bytes: The preview audio bytes.

        Raises:
            RuntimeError: If no preview URL is available.
        """
        # This will error out if the preview hasn't been generated
        previewURL = self.get_preview_url()
        if previewURL is None:
            raise RuntimeError("No preview URL available!")
        response = requests.get(previewURL, allow_redirects=True, timeout=requests_timeout)
        return response.content

    def play_preview_v2(self, playbackOptions:PlaybackOptions=PlaybackOptions()) -> sd.OutputStream:
        return play_audio_v2(self.get_preview_bytes(), playbackOptions)


class ElevenLabsEditableVoice(ElevenLabsVoice):
    """
    This class is shared by all the voices which can have their details edited and be deleted from an account.
    """
    def __init__(self, voiceData, linkedUser: ElevenLabsUser):
        super().__init__(voiceData, linkedUser)


    def edit_voice(self, newName:str = None, newLabels:dict[str, str] = None, description:str = None):
        """
        Edit the name/labels of the voice.

        Args:
            newName (str): The new name
            newLabels (str): The new labels
            description (str): The new description
        """
        currentInfo = self.update_data()
        payload = {
            "name": currentInfo["name"],
            "labels": currentInfo["labels"],
            "description": currentInfo["description"]
        }
        if newName is not None:
            payload["name"] = newName
        if newLabels is not None:
            if len(newLabels.keys()) > 5:
                raise ValueError("Too many labels! The maximum amount is 5.")
            payload["labels"] = newLabels
        if description is not None:
            payload["description"] = description
        _api_multipart("/voices/" + self._voiceID + "/edit", self._linkedUser.headers, data=payload)
    def delete_voice(self):
        """
        This function deletes the voice, and also sets the voiceID to be empty.
        """
        if self._category == "premade":
            raise RuntimeError("Cannot delete premade voices!")
        response = _api_del("/voices/" + self._voiceID, self._linkedUser.headers)
        self._voiceID = ""

class ElevenLabsDesignedVoice(ElevenLabsEditableVoice):
    """
    Represents a voice created via voice design.
    """
    def __init__(self, voiceData, linkedUser: ElevenLabsUser):
        super().__init__(voiceData, linkedUser)

    def get_share_link(self) -> str:
        """
        Returns the share link for the voice.

        Warning:
            If sharing is disabled, raises a RuntimeError.

        Returns:
            The share link for the voice.
        """
        sharingData = self.update_data()["sharing"]
        if sharingData is None or sharingData["status"] == "disabled":
            raise RuntimeError("This voice does not have sharing enabled.")

        publicOwnerID = sharingData["public_owner_id"]
        originalVoiceID = sharingData["original_voice_id"]

        return f"https://beta.elevenlabs.io/voice-lab/share/{publicOwnerID}/{originalVoiceID}"

class ElevenLabsProfessionalVoice(ElevenLabsEditableVoice):
    """
    Represents a voice created via professional voice cloning.
    """
    def __init__(self, voiceData, linkedUser: ElevenLabsUser):
        super().__init__(voiceData, linkedUser)

    def get_samples(self) -> list[ElevenLabsSample]:
        """
        Caution:
            There is an API bug here. The /voices/voiceID endpoint does not correctly return sample data for professional cloning voices.

        Returns:
            list[ElevenLabsSample]: The samples that make up this professional voice clone.
        """
        outputList = list()
        samplesData = self.update_data()["samples"]
        from elevenlabslib.ElevenLabsSample import ElevenLabsSample
        for sampleData in samplesData:
            outputList.append(ElevenLabsSample(sampleData, self))
        return outputList

    def get_high_quality_models(self) -> list[ElevenLabsModel]:
        return [model for model in self.linkedUser.get_models() if model.modelID in self.update_data()["high_quality_base_model_ids"]]

class ElevenLabsClonedVoice(ElevenLabsEditableVoice):
    """
    Represents a voice created via instant voice cloning.
    """
    def __init__(self, voiceData, linkedUser: ElevenLabsUser):
        super().__init__(voiceData, linkedUser)

    def get_samples(self) -> list[ElevenLabsSample]:
        """
        Returns:
            list[ElevenLabsSample]: The samples that make up this voice clone.
        """

        outputList = list()
        samplesData = self.update_data()["samples"]
        from elevenlabslib.ElevenLabsSample import ElevenLabsSample
        for sampleData in samplesData:
            outputList.append(ElevenLabsSample(sampleData, self))
        return outputList

    def add_samples_by_path(self, samples:list[str]|str):
        """
        This function adds samples to the current voice by their file paths.

        Args:
            samples (list[str]|str): A list with the file paths to the audio files or a str containing a single path.

        Raises:
            ValueError: If no samples are provided.

        """
        if isinstance(samples, str):
            samples = list(samples)

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
            samples (dict[str, bytes]): A dictionary of audio file names and their respective bytes.

        Raises:
            ValueError: If no samples are provided.

        """
        if len(samples.keys()) == 0:
            raise ValueError("Please add at least one sample!")

        payload = {"name":self.update_data()["name"]}   #Has to be up to date.
        files = list()
        for fileName, fileBytes in samples.items():
            files.append(("files", (fileName, io.BytesIO(fileBytes))))

        _api_multipart("/voices/" + self._voiceID + "/edit", self._linkedUser.headers, data=payload, filesData=files)



#This way lies only madness.

#This is to work around an issue. May god have mercy on my soul.
class BodgedSoundFile(sf.SoundFile):
    def buffer_read(self, frames=-1, dtype=None):
        from _soundfile import ffi as _ffi
        frames = self._check_frames(frames, fill_value=None)
        ctype = self._check_dtype(dtype)
        cdata = _ffi.new(ctype + '[]', frames * self.channels)
        read_frames = self._cdata_io('read', cdata, ctype, frames)
        assert read_frames == frames, _ffi.buffer(cdata)    #Return read data as exception.args[0]
        return _ffi.buffer(cdata)

    def read(self, frames=-1, dtype='float64', always_2d=False,
             fill_value=None, out=None):

        if out is None:
            frames = self._check_frames(frames, fill_value)
            out = self._create_empty_array(frames, always_2d, dtype)
        else:
            if frames < 0 or frames > len(out):
                frames = len(out)
        frames = self._array_io('read', out, frames)
        if len(out) > frames:
            if fill_value is None:
                out = out[:frames]
            else:
                out[frames:] = fill_value
        return out


class _AudioStreamer:
    def __init__(self, streamConnection: Union[requests.Response, websockets.sync.client.ClientConnection],
                 generation_options:GenerationOptions, websocket_options:WebsocketOptions, prompt: Union[str, Iterator[str], bytes, io.IOBase], prompting_options:PromptingOptions):
        self._events = dict()
        self._current_audio_ms = 0
        self.transcript_queue = queue.Queue()   #Holds the transcripts for the audio data
        self._enable_cutout = False
        self._prompting_options = prompting_options

        self._start_frame = None
        self._end_frame = None

        if prompting_options is not None:   #Sanity check
            if isinstance(prompt, Iterator) or not isinstance(prompt, SyncIterator):
                self._enable_cutout = True
                if prompting_options.pre_prompt == "":
                    self._start_frame = 0

        self._connection = streamConnection
        self._generation_options = generation_options
        self._sample_rate = int(generation_options.output_format.split("_")[1])
        self._websocket_options = websocket_options
        self._prompt = prompt

    def _check_position(self, curr_frame) -> (bool, int, int):
        start_delta = None
        end_delta = None
        if self._enable_cutout:
            frame_bool = False
            if self._start_frame is None:
                frame_bool = False  # No start time yet
            else:
                start_delta = curr_frame - self._start_frame
                if start_delta >= 0:
                    frame_bool = True  # After start time
                if self._end_frame is not None:  # If we have an end time
                    end_delta = curr_frame - self._end_frame
                    if end_delta >= 0:
                        frame_bool = False  # We're past the end time
        else:
            frame_bool = True

        check_info = {
            "start_frame": self._start_frame,
            "start_delta": start_delta,
            "end_frame": self._end_frame,
            "end_delta": end_delta,
            "curr_frame":curr_frame,
            "is_usable": frame_bool
        }
        logging.debug(check_info)

        return frame_bool, start_delta, end_delta

    def _cutout_data(self, curr_frame:int, data:Union[bytes, numpy.ndarray], framesize:int) -> (Union[bytes, numpy.ndarray], str):
        """
        Parameters:
            curr_frame (int): The position (at the start of data!)
            data (bytes|numpy.ndarray): The data to handle
            framesize (int): The framesize.
        Returns:
            A tuple with the modified data and an indicator of the action taken (None,start,stop,zero)
        """
        if not self._enable_cutout:
            return data, None

        datalen = 0
        if isinstance(data, bytes):
            datalen = len(data) // framesize
        elif isinstance(data, numpy.ndarray):
            framesize = 1   #Override it since we're working with frames directly
            if data.ndim == 1:
                datalen = len(data)
            elif data.ndim == 2:
                datalen = data.shape[0]

        #curr_frame -= datalen       #If we've read this chunk, then we're positioned _after_ it, so account for that.

        frame_bool, start_delta, end_delta = self._check_position(curr_frame)

        if start_delta is not None and start_delta < 0 and datalen > -start_delta:
            data_to_keep = (datalen + start_delta) * framesize
            if isinstance(data, bytes):
                return b'\x00' * (len(data) - data_to_keep) + data[-data_to_keep:], "start"
            else:  # numpy.ndarray
                kept_data = data[-data_to_keep:]
                empty_data = np.zeros_like(data)[:datalen - data_to_keep]
                return np.concatenate((empty_data, kept_data)), "start"

        elif end_delta is not None and end_delta < 0 and datalen > -end_delta:
            data_to_keep = (datalen + end_delta) * framesize
            if isinstance(data, bytes):
                return data[:data_to_keep] + b'\x00' * (len(data) - data_to_keep), "stop"
            else:  # numpy.ndarray
                kept_data = data[:data_to_keep]
                empty_data = np.zeros_like(data)[:len(data) - data_to_keep]
                return np.concatenate((kept_data, empty_data)), "stop"
        elif not frame_bool:
            if isinstance(data, bytes):
                data = b'\x00' * len(data)
            else:
                data = np.zeros_like(data)
            return data, "zero"

        return data, None

    def _stream_downloader_function(self):
        # This is the function running in the download thread.
        self._connection.raise_for_status()
        totalLength = 0
        logging.debug("Starting iter...")
        for chunk in self._connection.iter_content(chunk_size=_downloadChunkSize):
            self._stream_downloader_chunk_handler(chunk)
            totalLength += len(chunk)

        logging.debug("Download finished - " + str(totalLength) + ".")
        self._events["downloadDoneEvent"].set()
        return

    def _stream_downloader_function_websockets(self):
        totalLength = 0
        logging.debug("Starting iter...")

        def sender():
            for text_chunk in _text_chunker(self._prompt, self._generation_options):
                sent_data = dict(text=text_chunk, try_trigger_generation=self._websocket_options.try_trigger_generation)
                try:
                    self._connection.send(json.dumps(sent_data))
                except websockets.exceptions.ConnectionClosedError as e:
                    logging.exception(f"Generation failed, shutting down: {e}")
                    raise e

            self._connection.send(json.dumps(dict(text=""))) # Send end of stream

        sender_thread = threading.Thread(target=sender)
        sender_thread.start()

        while True:
            try:
                data = json.loads(self._connection.recv()) #We block because we know we're waiting on more messages.
                alignment_data = data.get("normalizedAlignment", None)
                if alignment_data is not None:
                    formatted_list = list()
                    for i in range(len(alignment_data["chars"])):
                        new_char = {
                            "character": alignment_data["chars"][i],
                            "start_time_ms": alignment_data["charStartTimesMs"][i] + self._current_audio_ms,
                            "duration_ms": alignment_data["charDurationsMs"][i]
                        }
                        formatted_list.append(new_char)
                        if self._enable_cutout:
                            if new_char["character"] == '"':
                                if self._start_frame is None:
                                    self._start_frame = math.ceil((new_char["start_time_ms"] + new_char["duration_ms"] * (1 - self._prompting_options.open_quote_duration_multiplier)) * self._sample_rate / 1000)
                                else:
                                    self._end_frame = math.floor((new_char["start_time_ms"] + new_char["duration_ms"] * self._prompting_options.close_quote_duration_multiplier) * self._sample_rate / 1000)

                    self._current_audio_ms = formatted_list[-1]["start_time_ms"] + formatted_list[-1]["duration_ms"]

                    if self.transcript_queue is not None:
                        self.transcript_queue.put(formatted_list)

                audio_data = data.get("audio", None)
                if audio_data:
                    chunk = base64.b64decode(data["audio"])
                    self._stream_downloader_chunk_handler(chunk)
                    totalLength += len(chunk)


                is_final = data.get("isFinal", False)
                if is_final:
                    logging.debug("websocket final message recieved.")
                    break   #We break out early.
            except websockets.exceptions.ConnectionClosed:
                break

        self.transcript_queue.put(None) #We're done with the transcripts

        logging.debug("Download finished - " + str(totalLength) + ".")
        self._events["downloadDoneEvent"].set()
        sender_thread.join()    #Just in case something went wrong.

    def _stream_downloader_chunk_handler(self, chunk):
        pass

class _DownloadStreamer(_AudioStreamer):
    def __init__(self, streamConnection: Union[requests.Response, websockets.sync.client.ClientConnection],
                 generation_options:GenerationOptions, websocket_options:WebsocketOptions, prompt: Union[str, Iterator[str], bytes, io.IOBase], prompting_options:PromptingOptions):
        super().__init__(streamConnection, generation_options, websocket_options, prompt, prompting_options)
        self._events: dict[str, threading.Event] = {
            "downloadDoneEvent": threading.Event()
        }
        self.destination_queue = queue.Queue()
        if "mp3" in generation_options.output_format.lower():
            self._framesize = 4
        else:
            self._framesize = 2
        self._audio_length = 0



    def begin_streaming(self):
        for eventName, event in self._events.items():
            event.clear()

        logging.debug("Starting playback...")
        if isinstance(self._connection, requests.Response):
            self._stream_downloader_function()
        else:
            self._stream_downloader_function_websockets()
        logging.debug("Stream done - putting None in the queue.")
        self.destination_queue.put(None)
        return

    def _stream_downloader_chunk_handler(self, chunk):
        self.destination_queue.put(chunk)


#TODO (maybe): Refactor _Mp3Streamer and _RawStreamer to just use a _NumpyStreamer.
class _Mp3Streamer(_AudioStreamer):

    def __init__(self, playbackOptions:PlaybackOptions, streamConnection: Union[requests.Response, websockets.sync.client.ClientConnection],
                 generation_options:GenerationOptions, websocket_options:WebsocketOptions, prompt: Union[str, Iterator[str], bytes, io.IOBase], prompting_options:PromptingOptions):
        super().__init__(streamConnection, generation_options, websocket_options, prompt, prompting_options)
        self._dtype= "float32"
        self._q = queue.Queue()
        self._bytesFile = io.BytesIO()
        self._bytesSoundFile: Optional[BodgedSoundFile] = None  # Needs to be created later.
        self._bytesLock = threading.Lock()
        self._onPlaybackStart = playbackOptions.onPlaybackStart
        self._onPlaybackEnd = playbackOptions.onPlaybackEnd
        self._frameSize = 0
        self.last_recreated_pos = 0 #Handling for a bug.
        self._deviceID = playbackOptions.portaudioDeviceID or sd.default.device

        self._events: dict[str, threading.Event] = {
            "playbackFinishedEvent": threading.Event(),
            "headerReadyEvent": threading.Event(),
            "soundFileReadyEvent": threading.Event(),
            "downloadDoneEvent": threading.Event(),
            "blockDataAvailable": threading.Event(),
            "playbackStartFired": threading.Event()
        }

    def _stream_downloader_function(self):
        super()._stream_downloader_function()
        self._events["blockDataAvailable"].set()    #This call only happens once the download is entirely complete.
        return

    def _stream_downloader_function_websockets(self):
        super()._stream_downloader_function_websockets()
        self._events["blockDataAvailable"].set()    #This call only happens once the download is entirely complete.

    def begin_streaming(self, future:concurrent.futures.Future):
        # Clean all the buffers and reset all events.
        # Note: text and custom_pronunciations are unused if it's not doing input_streaming - I just pass them anyway out of convenience.
        self._q = queue.Queue()
        self._bytesFile = io.BytesIO()
        self._bytesSoundFile: Optional[BodgedSoundFile] = None  # Needs to be created later.
        for eventName, event in self._events.items():
            event.clear()

        if isinstance(self._connection, requests.Response):
            downloadThread = threading.Thread(target=self._stream_downloader_function)
        else:
            downloadThread = threading.Thread(target=self._stream_downloader_function_websockets)
        downloadThread.start()

        while True:
            logging.debug("Waiting for header event...")
            self._events["headerReadyEvent"].wait()
            logging.debug("Header maybe ready?")
            try:
                with self._bytesLock:
                    self._bytesSoundFile = BodgedSoundFile(self._bytesFile)
                    logging.debug("File created (" + str(self._bytesFile.tell()) + " bytes read).")
                    self._frameSize = self._bytesSoundFile.channels * sf._ffi.sizeof(self._bytesSoundFile._check_dtype(self._dtype))

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
            samplerate=self._bytesSoundFile.samplerate, blocksize=_playbackBlockSize,
            device=self._deviceID, channels=self._bytesSoundFile.channels, dtype=self._dtype,
            callback=self._stream_playback_callback, finished_callback=self._events["playbackFinishedEvent"].set)

        future.set_result(stream)
        logging.debug("Starting playback...")
        with stream:

            while True:
                try:
                    data = self._get_data_from_download_thread()
                    #if self._start_frame is not None:

                    with self._bytesLock:
                        original_data_length = len(data)
                        cur_pos = self._bytesSoundFile.tell()-original_data_length//self._frameSize
                        data, action_taken = self._cutout_data(cur_pos, data, self._frameSize)
                        if action_taken is not None:
                            silence_chunk = b'\x00' * original_data_length
                            if action_taken == "start":
                                self._q.put(silence_chunk)
                            if action_taken == "stop":
                                self._q.put(data)
                                for _ in range(2):
                                    self._q.put(silence_chunk)
                                data = silence_chunk
                except RuntimeError as e:
                    logging.debug("File was looping at the end. Exiting.")
                    self._q.put(e)
                    break

                if len(data) == _playbackBlockSize*self._frameSize:
                    logging.debug("Putting " + str(len(data)) + " bytes in queue.")
                    self._q.put(data)
                else:
                    logging.debug("Got back less data than expected, check if we're at the end...")
                    with self._bytesLock:
                        # This needs to use bytes rather than frames left, as sometimes the number of frames left is wrong.
                        curPos = self._bytesFile.tell()
                        endPos = self._bytesFile.seek(0, os.SEEK_END)
                        self._bytesFile.seek(curPos)
                        if endPos == curPos and self._events["downloadDoneEvent"].is_set():
                            logging.debug("We're at the end.")
                            if len(data) > 0:
                                logging.debug("Still some data left, writing it...")
                                #logging.debug("Putting " + str(len(data)) +
                                #              " bytes in queue.")
                                curr_frame = curPos - len(data)//self._frameSize
                                data, action = self._cutout_data(curr_frame, data, self._frameSize)
                                self._q.put(data)
                            break
                        else:
                            logging.debug("We're not at the end, yet we recieved less data than expected. This is a bug that was introduced with the update.")
            logging.debug("While loop done.")
            self._events["playbackFinishedEvent"].wait()  # Wait until playback is finished
            self._onPlaybackEnd()
            logging.debug(stream.active)
        logging.debug("Stream done.")
        return

    def _stream_downloader_chunk_handler(self, chunk:bytes):
        #Split the code for easier handling
        if self._events["headerReadyEvent"].is_set() and not self._events["soundFileReadyEvent"].is_set():
            logging.debug("HeaderReady is set, but waiting for the soundfile...")
            self._events["soundFileReadyEvent"].wait()  # Wait for the soundfile to be created.
            if not self._events["headerReadyEvent"].is_set():
                logging.debug("headerReady was cleared by the playback thread. Header data still missing, download more.")
                self._events["soundFileReadyEvent"].clear()

        if len(chunk) != _downloadChunkSize:
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
                if endPos - lastReadPos > _playbackBlockSize:  # We've read enough data to fill up a block, alert the other thread.
                    logging.debug("Raise available data event - " + str(endPos - lastReadPos) + " bytes available")
                    self._events["blockDataAvailable"].set()

    def _stream_playback_callback(self, outdata, frames, timeData, status):
        assert frames == _playbackBlockSize
        readData = None
        while True:
            try:
                if self._events["downloadDoneEvent"].is_set():
                    readData = self._q.get_nowait()
                else:
                    readData = self._q.get(timeout=5)    #Download isn't over so we may have to wait.

                if isinstance(readData, RuntimeError):
                    logging.warning("File was looping. Stopping.")
                    raise sd.CallbackStop
                else:
                    if isinstance(readData, numpy.ndarray):
                        readData = readData.reshape(-1, self._bytesSoundFile.channels)

                    if len(readData) == 0 and not self._events["downloadDoneEvent"].is_set():
                        logging.warning("An empty item got into the queue. This shouldn't happen, but let's just skip it.")
                        continue
                break
            except queue.Empty as e:
                if self._events["downloadDoneEvent"].is_set():
                    logging.debug("Download (and playback) finished.")  # We're done.
                    raise sd.CallbackStop
                else:
                    logging.error("Could not get an item within the timeout. This could lead to audio issues.")
                    continue
                    #raise sd.CallbackAbort
        #We've read an item from the queue.

        if not self._events["playbackStartFired"].is_set(): #Ensure the callback only fires once.
            self._events["playbackStartFired"].set()
            logging.debug("Firing onPlaybackStart...")
            self._onPlaybackStart()

        # Last read chunk was smaller than it should've been. It's either EOF or that stupid soundFile bug.
        if 0 < len(readData) < len(outdata):
            logging.debug("Data read smaller than it should've been.")
            logging.debug(f"Read {len(readData)} bytes but expected {len(outdata)}, padding...")

            outdata[:len(readData)] = readData
            if isinstance(outdata, numpy.ndarray):
                outdata[len(readData):].fill(0)
            else:
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
                    logging.error("...Read no data but the download isn't over? Panic. Just send silence.")
                    if isinstance(outdata, numpy.ndarray):
                        outdata[len(readData):].fill(0)
                    else:
                        outdata[len(readData):] = b'\x00' * (len(outdata) - len(readData))
        else:
            outdata[:] = readData



    # Note: A lot of this function is just workarounds for bugs, all of which are described in this issue: https://github.com/bastibe/python-soundfile/issues/379
    # THIS FUNCTION ASSUMES YOU'VE GIVEN THE THREAD RUNNING IT THE _bytesLock LOCK.
    def _assertionerror_workaround(self, dataToRead:int=-1, dtype=None, preReadFramePos=-1, preReadBytesPos=-1) -> bytes:
        # The bug happened, so we must be at a point in the file where the reading fails.

        logging.debug("The following is some logging for a new and fun soundfile bug, which I (poorly) worked around. Lovely.")
        logging.debug(f"Before the bug: frame {preReadFramePos} (byte {preReadBytesPos})")
        logging.debug(f"After the bug: frame {self._bytesSoundFile.tell()} (byte {self._bytesFile.tell()})")

        # Release the lock on the underlying BytesIO to allow the download thread to download a bit more of the file.
        self._bytesLock.release()
        if not self._events["downloadDoneEvent"].is_set():
            # Wait for the next block to be downloaded.
            logging.debug("Fun bug happened before the download was over. Waiting for blockDataAvailable.")
            self._events["blockDataAvailable"].clear()
            self._events["blockDataAvailable"].wait()
        else:
            # Wait.
            logging.debug("Fun bug happened AFTER the download was over. Continue.")


        self._bytesLock.acquire()

        # Let's seek back and re-create the SoundFile, so that we're sure it's fully synched up.
        self._bytesFile.seek(0)
        newSF = BodgedSoundFile(self._bytesFile, mode="r")
        newSF.seek(preReadFramePos)
        del self._bytesSoundFile
        self._bytesSoundFile = newSF
        new_bytes_pos = self._bytesFile.tell()
        logging.debug(f"Done recreating, now at {self._bytesSoundFile.tell()} (byte {self._bytesFile.tell()}).")
        if self.last_recreated_pos == new_bytes_pos and self._events["downloadDoneEvent"].is_set():
            #If the bug happens twice, at the same spot, once hte file is fully downloaded, just assume it's broken.
            raise RuntimeError("File is looping at the end.")
        else:
            self.last_recreated_pos = new_bytes_pos
        # Try reading the data again. If it works, good.
        try:
            readData = self._bytesSoundFile.buffer_read(dataToRead, dtype=dtype)
        except (AssertionError, soundfile.LibsndfileError) as ea:
            # If it fails, get the partial data from the exception args.
            readData = ea.args[0]
        return readData

    def _soundFile_read_and_fix(self, dataToRead:int=-1, dtype=None):
        if dtype is None:
            dtype = self._dtype
        preReadFramePos = self._bytesSoundFile.tell()
        preReadBytesPos = self._bytesFile.tell()

        try:
            readData = self._bytesSoundFile.buffer_read(dataToRead, dtype=dtype)
        except (AssertionError, soundfile.LibsndfileError):
            #The bug happened, so we must be at a point in the file where the reading fails.
            readData = self._assertionerror_workaround(dataToRead, dtype, preReadFramePos, preReadBytesPos)


        #This is the handling for the bug that's described in the rest of the issue. Irrelevant to this new one.
        if dataToRead * self._frameSize != len(readData):
            logging.debug(f"Expected {dataToRead * self._frameSize} bytes, but got back {len(readData)}")
        if len(readData) < dataToRead * self._frameSize:
            logging.debug("Insufficient data read.")
            curPos = self._bytesFile.tell()
            endPos = self._bytesFile.seek(0, os.SEEK_END)
            if curPos != endPos:
                logging.debug("We're not at the end of the file. Check if we're out of frames.")
                logging.debug("Recreating soundfile...")
                self._bytesFile.seek(0)
                newSF = BodgedSoundFile(self._bytesFile, mode="r")
                newSF.seek(self._bytesSoundFile.tell() - int(len(readData) / self._frameSize))
                if newSF.frames > self._bytesSoundFile.frames:
                    logging.debug("Frame counter was outdated.")
                    del self._bytesSoundFile
                    self._bytesSoundFile = newSF

                    preReadFramePos = self._bytesSoundFile.tell()
                    preReadBytesPos = self._bytesFile.tell()

                    try:
                        readData = self._bytesSoundFile.buffer_read(dataToRead, dtype=dtype)
                    except (AssertionError, soundfile.LibsndfileError):
                        readData = self._assertionerror_workaround(dataToRead, dtype, preReadFramePos, preReadBytesPos)
                    logging.debug("Now read " + str(len(readData)) +
                          " bytes. I sure hope that number isn't zero.")
                else:
                    del newSF
        return readData

    def _get_data_from_download_thread(self) -> bytes:
        self._events["blockDataAvailable"].wait()  # Wait until a block of data is available.
        self._bytesLock.acquire()
        readData = self._soundFile_read_and_fix(_playbackBlockSize)

        currentPos = self._bytesFile.tell()
        self._bytesFile.seek(0, os.SEEK_END)
        endPos = self._bytesFile.tell()
        #logging.debug("Remaining file length: " + str(endPos - currentPos) + "\n")
        self._bytesFile.seek(currentPos)
        remainingBytes = endPos - currentPos

        if remainingBytes < _playbackBlockSize and not self._events["downloadDoneEvent"].is_set():
            logging.debug("Marking no available blocks...")
            self._events["blockDataAvailable"].clear()  # Download isn't over and we've consumed enough data to where there isn't another block available.

        logging.debug("Read bytes: " + str(len(readData)) + "\n")

        self._bytesLock.release()
        return readData

class _RAWStreamer(_AudioStreamer):
    def __init__(self, playbackOptions:PlaybackOptions, streamConnection: Union[requests.Response, websockets.sync.client.ClientConnection],
                 generation_options:GenerationOptions, websocket_options:WebsocketOptions, prompt: Union[str, Iterator[str], bytes, io.IOBase], prompting_options:PromptingOptions):
        super().__init__(streamConnection, generation_options, websocket_options, prompt, prompting_options)
        self._q = queue.Queue()
        self._onPlaybackStart = playbackOptions.onPlaybackStart
        self._onPlaybackEnd = playbackOptions.onPlaybackEnd
        self._dtype = "int16"

        parts = generation_options.output_format.lower().split("_")
        self._subtype = parts[0]
        self._sample_rate = int(parts[1])

        self._deviceID = playbackOptions.portaudioDeviceID or sd.default.device
        self._channels = 1
        self._frameSize = 2
        self._events: dict[str, threading.Event] = {
            "playbackFinishedEvent": threading.Event(),
            "downloadDoneEvent": threading.Event(),
            "playbackStartFired": threading.Event(),
            "blockDataAvailable": threading.Event()
        }
        self._buffer = b""
        self._audio_length = 0

    def _stream_downloader_function(self):
        super()._stream_downloader_function()
        self._stream_downloader_chunk_handler(b"")

    def _stream_downloader_function_websockets(self):
        super()._stream_downloader_function_websockets()
        self._stream_downloader_chunk_handler(b"")

    def begin_streaming(self, future:concurrent.futures.Future):
        # Clean all the buffers and reset all events.
        # Note: text is unused if it's not doing input_streaming - I just pass it anyway out of convenience.
        self._q = queue.Queue()
        self._buffer = b""
        for eventName, event in self._events.items():
            event.clear()

        stream = sd.OutputStream(
            samplerate=self._sample_rate, blocksize=_playbackBlockSize,
            device=self._deviceID, channels=self._channels, dtype=self._dtype,
            callback=self._stream_playback_callback, finished_callback=self._events["playbackFinishedEvent"].set)
        future.set_result(stream)
        logging.debug("Starting playback...")
        with stream:
            if isinstance(self._connection, requests.Response):
                self._stream_downloader_function()
            else:
                self._stream_downloader_function_websockets()

            self._events["playbackFinishedEvent"].wait()  # Wait until playback is finished
            self._onPlaybackEnd()

        logging.debug("Stream done.")
        return

    def _stream_downloader_chunk_handler(self, chunk:bytes):
        #Split the code for easier handling

        if self._subtype.lower() == "ulaw":
            chunk = audioop.ulaw2lin(chunk, 2)
        self._buffer += chunk
        self._audio_length += len(chunk)

        while len(self._buffer) >= _playbackBlockSize*self._frameSize:
            curr_pos = (self._audio_length-len(self._buffer)) // self._frameSize
            frame_data, self._buffer = self._buffer[:_playbackBlockSize*self._frameSize], self._buffer[_playbackBlockSize*self._frameSize:]
            frame_data, action_taken = self._cutout_data(curr_pos, frame_data, self._frameSize)
            audioData = numpy.frombuffer(frame_data, dtype=self._dtype)
            audioData = audioData.reshape(-1, self._channels)

            self._q.put(audioData)

        if self._events["downloadDoneEvent"].is_set() and len(self._buffer) > 0:
            audioData = numpy.frombuffer(self._buffer, dtype=self._dtype)
            curr_pos = (self._audio_length - len(self._buffer)) // self._frameSize
            audioData, action_taken = self._cutout_data(curr_pos, audioData, self._frameSize)
            self._q.put(audioData.reshape(-1, self._channels))
            # Pad the end of the audio with silence to avoid the looping final chunk.s
            silence_chunk = np.zeros(_playbackBlockSize * self._channels, dtype=self._dtype).reshape(-1, self._channels)
            for _ in range(2):
                self._q.put(silence_chunk)

    def _stream_playback_callback(self, outdata, frames, timeData, status):
        assert frames == _playbackBlockSize
        readData = None
        while True:
            try:
                if self._events["downloadDoneEvent"].is_set():
                    readData = self._q.get_nowait()
                else:
                    readData = self._q.get(timeout=5)    #Download isn't over so we may have to wait.

                if len(readData) == 0 and not self._events["downloadDoneEvent"].is_set():
                    logging.error("An empty item got into the queue. This shouldn't happen, but let's just skip it.")
                    continue

                break
            except queue.Empty as e:
                if self._events["downloadDoneEvent"].is_set():
                    logging.debug("Download (and playback) finished.")  # We're done.
                    raise sd.CallbackStop
                else:
                    logging.error("Could not get an item within the timeout. This could lead to audio issues.")
                    continue
                    #raise sd.CallbackAbort
        #We've read an item from the queue.

        if not self._events["playbackStartFired"].is_set(): #Ensure the callback only fires once.
            self._events["playbackStartFired"].set()
            logging.debug("Firing onPlaybackStart...")
            self._onPlaybackStart()

        # Last read chunk was smaller than it should've been. It's either EOF or that stupid soundFile bug.
        if 0 < len(readData) < len(outdata):
            logging.debug("Data read smaller than it should've been.")
            logging.debug(f"Read {len(readData)} bytes but expected {len(outdata)}, padding...")

            outdata[:len(readData)] = readData
            outdata[len(readData):].fill(0)
        elif len(readData) == 0:
            logging.warning("Callback got empty data from the queue.")
        else:
            outdata[:] = readData


#Is this a ton of duplicate code? Yes.
#Do I want to spend god knows how many hours finagling this finnicky mp3 streaming code to unify it? No.
class _NumpyStreamer(_AudioStreamer):
    def __init__(self, streamConnection: Union[requests.Response, websockets.sync.client.ClientConnection],
                 generation_options:GenerationOptions, websocket_options:WebsocketOptions, prompt: Union[str, Iterator[str], bytes, io.IOBase], prompting_options:PromptingOptions):
        super().__init__(streamConnection, generation_options, websocket_options, prompt, prompting_options)

        parts = generation_options.output_format.lower().split("_")
        self._subtype = parts[0]

        self._events: dict[str, threading.Event] = {
            "headerReadyEvent": threading.Event(),
            "soundFileReadyEvent": threading.Event(),
            "downloadDoneEvent": threading.Event(),
            "blockDataAvailable": threading.Event()
        }

        self.destination_queue = queue.Queue()
        if "mp3" in generation_options.output_format.lower():
            self._audio_type = "mp3"
            self._frameSize = 4
            self._dtype = "float32"
        else:
            self._audio_type = "raw"
            self._frameSize = 2
            self._dtype = "int16"

        self._channels = 1
        self._buffer = b""
        self._audio_length = 0

        self._bytesFile = io.BytesIO()
        self._bytesSoundFile: Optional[BodgedSoundFile] = None  # Needs to be created later.
        self._bytesLock = threading.Lock()

    def _stream_downloader_function(self):
        super()._stream_downloader_function()
        self._events["blockDataAvailable"].set()    #This call only happens once the download is entirely complete.
        return

    def _stream_downloader_function_websockets(self):
        super()._stream_downloader_function_websockets()
        self._events["blockDataAvailable"].set()    #This call only happens once the download is entirely complete.


    def _assertionerror_workaround(self, dataToRead:int=-1, dtype=None, preReadFramePos=-1, preReadBytesPos=-1) -> bytes:
        # The bug happened, so we must be at a point in the file where the reading fails.

        logging.debug("The following is some logging for a new and fun soundfile bug, which I (poorly) worked around. Lovely.")
        logging.debug(f"Before the bug: frame {preReadFramePos} (byte {preReadBytesPos})")
        logging.debug(f"After the bug: frame {self._bytesSoundFile.tell()} (byte {self._bytesFile.tell()})")

        # Release the lock on the underlying BytesIO to allow the download thread to download a bit more of the file.
        self._bytesLock.release()
        if not self._events["downloadDoneEvent"].is_set():
            # Wait for the next block to be downloaded.
            logging.debug("Fun bug happened before the download was over. Waiting for blockDataAvailable.")
            self._events["blockDataAvailable"].clear()
            self._events["blockDataAvailable"].wait()
        else:
            # Wait.
            logging.debug("Fun bug happened AFTER the download was over. Continue.")


        self._bytesLock.acquire()

        # Let's seek back and re-create the SoundFile, so that we're sure it's fully synched up.
        self._bytesFile.seek(0)
        newSF = BodgedSoundFile(self._bytesFile, mode="r")
        newSF.seek(preReadFramePos)
        del self._bytesSoundFile
        self._bytesSoundFile = newSF
        new_bytes_pos = self._bytesFile.tell()
        logging.debug(f"Done recreating, now at {self._bytesSoundFile.tell()} (byte {self._bytesFile.tell()}).")
        if self.last_recreated_pos == new_bytes_pos and self._events["downloadDoneEvent"].is_set():
            #If the bug happens twice, at the same spot, once hte file is fully downloaded, just assume it's broken.
            raise RuntimeError("File is looping at the end.")
        else:
            self.last_recreated_pos = new_bytes_pos
        # Try reading the data again. If it works, good.
        try:
            readData = self._bytesSoundFile.read(dataToRead, dtype=dtype)
        except (AssertionError, soundfile.LibsndfileError) as ea:
            # If it fails, get the partial data from the exception args.
            readData = ea.args[0]
        return readData

    def _soundFile_read_and_fix(self, dataToRead:int=-1, dtype=None):
        if dtype is None:
            dtype = self._dtype
        preReadFramePos = self._bytesSoundFile.tell()
        preReadBytesPos = self._bytesFile.tell()

        try:
            readData = self._bytesSoundFile.read(dataToRead, dtype=dtype)
        except (AssertionError, soundfile.LibsndfileError):
            #The bug happened, so we must be at a point in the file where the reading fails.
            readData = self._assertionerror_workaround(dataToRead, dtype, preReadFramePos, preReadBytesPos)


        #This is the handling for the bug that's described in the rest of the issue. Irrelevant to this new one.
        if dataToRead != len(readData):
            logging.debug(f"Expected {dataToRead} bytes, but got back {len(readData)}")
        if len(readData) < dataToRead:
            logging.debug("Insufficient data read.")
            curPos = self._bytesFile.tell()
            endPos = self._bytesFile.seek(0, os.SEEK_END)
            if curPos != endPos:
                logging.debug("We're not at the end of the file. Check if we're out of frames.")
                logging.debug("Recreating soundfile...")
                self._bytesFile.seek(0)
                newSF = BodgedSoundFile(self._bytesFile, mode="r")
                newSF.seek(self._bytesSoundFile.tell() - int(len(readData)))
                if newSF.frames > self._bytesSoundFile.frames:
                    logging.debug("Frame counter was outdated.")
                    del self._bytesSoundFile
                    self._bytesSoundFile = newSF

                    preReadFramePos = self._bytesSoundFile.tell()
                    preReadBytesPos = self._bytesFile.tell()

                    try:
                        readData = self._bytesSoundFile.read(dataToRead, dtype=dtype)
                    except (AssertionError, soundfile.LibsndfileError):
                        readData = self._assertionerror_workaround(dataToRead, dtype, preReadFramePos, preReadBytesPos)
                    logging.debug("Now read " + str(len(readData)) +
                          " bytes. I sure hope that number isn't zero.")
                else:
                    del newSF
        return readData


    def _get_data_from_download_thread(self) -> bytes:
        self._events["blockDataAvailable"].wait()  # Wait until a block of data is available.
        self._bytesLock.acquire()
        readData = self._soundFile_read_and_fix(_playbackBlockSize)

        currentPos = self._bytesFile.tell()
        self._bytesFile.seek(0, os.SEEK_END)
        endPos = self._bytesFile.tell()
        #logging.debug("Remaining file length: " + str(endPos - currentPos) + "\n")
        self._bytesFile.seek(currentPos)
        remainingBytes = endPos - currentPos

        if remainingBytes < _playbackBlockSize and not self._events["downloadDoneEvent"].is_set():
            logging.debug("Marking no available blocks...")
            self._events["blockDataAvailable"].clear()  # Download isn't over and we've consumed enough data to where there isn't another block available.

        logging.debug("Read bytes: " + str(len(readData)) + "\n")

        self._bytesLock.release()
        return readData

    def begin_streaming(self):
        if self._audio_type == "raw":
            for eventName, event in self._events.items():
                event.clear()

            if isinstance(self._connection, requests.Response):
                self._stream_downloader_function()
            else:
                self._stream_downloader_function_websockets()
            logging.debug("Stream done - putting None in the queue.")
            self.destination_queue.put(None)
        else:
            self._bytesFile = io.BytesIO()
            self._bytesSoundFile: Optional[BodgedSoundFile] = None  # Needs to be created later.
            for eventName, event in self._events.items():
                event.clear()

            if isinstance(self._connection, requests.Response):
                downloadThread = threading.Thread(target=self._stream_downloader_function)
            else:
                downloadThread = threading.Thread(target=self._stream_downloader_function_websockets)
            downloadThread.start()

            while True:
                logging.debug("Waiting for header event...")
                self._events["headerReadyEvent"].wait()
                logging.debug("Header maybe ready?")
                try:
                    with self._bytesLock:
                        self._bytesSoundFile = BodgedSoundFile(self._bytesFile)
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

            while True:
                try:
                    data = self._get_data_from_download_thread()
                    # if self._start_frame is not None:

                    with self._bytesLock:
                        original_data_length = len(data)
                        cur_pos = self._bytesSoundFile.tell() - original_data_length
                        data, action_taken = self._cutout_data(cur_pos, data, self._frameSize)
                except RuntimeError as e:
                    logging.debug("File was looping at the end. Exiting.")
                    break

                if len(data) == _playbackBlockSize:
                    logging.debug("Putting " + str(len(data)) + " bytes in queue.")
                    self.destination_queue.put(data)
                else:
                    logging.debug("Got back less data than expected, check if we're at the end...")
                    with self._bytesLock:
                        # This needs to use bytes rather than frames left, as sometimes the number of frames left is wrong.
                        curPos = self._bytesFile.tell()
                        endPos = self._bytesFile.seek(0, os.SEEK_END)
                        self._bytesFile.seek(curPos)
                        if endPos == curPos and self._events["downloadDoneEvent"].is_set():
                            logging.debug("We're at the end.")
                            if len(data) > 0:
                                logging.debug("Still some data left, writing it...")
                                # logging.debug("Putting " + str(len(data)) +
                                #              " bytes in queue.")
                                curr_frame = curPos - len(data)
                                data, action = self._cutout_data(curr_frame, data, self._frameSize)
                                self.destination_queue.put(data)
                            break
                        else:
                            logging.debug("We're not at the end, yet we recieved less data than expected. This is a bug that was introduced with the update.")
            logging.debug("While loop done.")
            self.destination_queue.put(None)
        return

    def _stream_downloader_chunk_handler(self, chunk):
        if self._audio_type == "raw":
            if self._subtype.lower() == "ulaw":
                chunk = audioop.ulaw2lin(chunk, 2)
            self._buffer += chunk
            self._audio_length += len(chunk)

            while len(self._buffer) >= _playbackBlockSize*self._frameSize:
                curr_pos = (self._audio_length-len(self._buffer)) // self._frameSize
                frame_data, self._buffer = self._buffer[:_playbackBlockSize*self._frameSize], self._buffer[_playbackBlockSize*self._frameSize:]
                frame_data, action_taken = self._cutout_data(curr_pos, frame_data, self._frameSize)
                audioData = numpy.frombuffer(frame_data, dtype=self._dtype)
                audioData = audioData.reshape(-1, self._channels)
                audioData = audioData.astype(np.float32)
                audioData /= np.iinfo(np.int16).max
                if action_taken is None or action_taken != "zero":
                    self.destination_queue.put(audioData)
                if action_taken is not None and action_taken == "stop":
                    self.destination_queue.put(None)

            if self._events["downloadDoneEvent"].is_set() and len(self._buffer) > 0:
                audioData = numpy.frombuffer(self._buffer, dtype=self._dtype)
                curr_pos = (self._audio_length - len(self._buffer)) // self._frameSize
                audioData, action_taken = self._cutout_data(curr_pos, audioData, self._frameSize)
                audioData = audioData.reshape(-1, self._channels)
                # Normalize to float32
                audioData = audioData.astype(np.float32)
                audioData /= np.iinfo(np.int16).max
                if action_taken is None or action_taken != "zero":
                    self.destination_queue.put(audioData)
                # Pad the end of the audio with silence to avoid the looping final chunk.s
                silence_chunk = np.zeros(_playbackBlockSize * self._channels, dtype=self._dtype).reshape(-1, self._channels)
                silence_chunk = silence_chunk.astype(np.float32)
                silence_chunk /= np.iinfo(np.int16).max
                for _ in range(2):
                    self.destination_queue.put(silence_chunk)
                self.destination_queue.put(None)
        else:
            if self._events["headerReadyEvent"].is_set() and not self._events["soundFileReadyEvent"].is_set():
                logging.debug("HeaderReady is set, but waiting for the soundfile...")
                self._events["soundFileReadyEvent"].wait()  # Wait for the soundfile to be created.
                if not self._events["headerReadyEvent"].is_set():
                    logging.debug("headerReady was cleared by the playback thread. Header data still missing, download more.")
                    self._events["soundFileReadyEvent"].clear()

            if len(chunk) != _downloadChunkSize:
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
                    if endPos - lastReadPos > _playbackBlockSize:  # We've read enough data to fill up a block, alert the other thread.
                        logging.debug("Raise available data event - " + str(endPos - lastReadPos) + " bytes available")
                        self._events["blockDataAvailable"].set()


class _Mp3Streamer2(_NumpyStreamer):
    pass