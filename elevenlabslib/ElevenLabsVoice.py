from __future__ import annotations

import base64
import concurrent.futures
import datetime
import os
import queue

import threading
import time
from concurrent.futures import Future
from typing import Optional, Tuple, Any, Iterator
from warnings import warn

import numpy
import requests
import soundfile as sf
import sounddevice as sd

from typing import TYPE_CHECKING

import websockets
from websockets.sync.client import connect

from elevenlabslib.ElevenLabsModel import ElevenLabsModel

if TYPE_CHECKING:
    from elevenlabslib.ElevenLabsSample import ElevenLabsSample
    from elevenlabslib.ElevenLabsUser import ElevenLabsUser
    from elevenlabslib.ElevenLabsHistoryItem import ElevenLabsHistoryItem

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
        if self._settings is None:  # TODO: Remove this once this no longer happens (aka, once the bug with the /voices endpoint is fixed)
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

    def _generate_payload(self, prompt:str, generationOptions:GenerationOptions=None):
        """
        Generates the payload for the text-to-speech API call.

        Args:
            prompt (str): The prompt to generate speech for.
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
            #The user overrode some voice settings, but not all of them. Let's fetch the others.
            currentSettings = self.settings
            voice_settings = dict()
            for key, currentValue in currentSettings.items():
                overriddenValue = getattr(generationOptions, key, None)
                voice_settings[key] = overriddenValue if overriddenValue is not None else currentValue

        model_id = generationOptions.model_id
        payload = {"text": prompt, "model_id": model_id}
        if voice_settings is not None:
            payload["voice_settings"] = voice_settings

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
        websocket = connect(
            websocketURL,
            additional_headers=self.linkedUser.headers
        )
        websocket.send(json.dumps(BOS))

        return websocket

    def generate_to_historyID(self, prompt: str, stability: Optional[float] = None, similarity_boost: Optional[float] = None, model_id: str = "eleven_monolingual_v1", latencyOptimizationLevel:int=0) -> str:
        warn("This function is deprecated. Please use generate_to_historyID_v2() instead, which supports the new options for the v2 models. See the porting guide on https://elevenlabslib.readthedocs.io for more information.", DeprecationWarning)

        return self.generate_to_historyID_v2(prompt, GenerationOptions(model_id, latencyOptimizationLevel, stability, similarity_boost))

    def generate_to_historyID_v2(self, prompt: str, generationOptions:GenerationOptions=None) -> (str, requests.Response):
        """
        Generate audio bytes from the given prompt and returns the historyItemID corresponding to it.

        Parameters:
            prompt (str): The text prompt to generate audio from.
            generationOptions (GenerationOptions): Options for the audio generation such as the model to use and the voice settings.
        Returns:
            The ID for the new HistoryItem
            The full response object
        """
        if generationOptions is None:
            generationOptions = GenerationOptions()

        payload = self._generate_payload(prompt, generationOptions)
        params = self._generate_parameters(generationOptions)

        requestFunction = lambda: _api_json("/text-to-speech/" + self._voiceID + "/stream", self._linkedUser.headers, jsonData=payload, stream=True, params=params)
        generationID = f"{self.voiceID} - {prompt} - {time.time()}"
        response = _api_tts_with_concurrency(requestFunction, generationID, self._linkedUser.generation_queue)

        return response.headers["history-item-id"], response

    def generate_audio(self, prompt: str, stability: Optional[float] = None, similarity_boost: Optional[float] = None, model_id: str = "eleven_monolingual_v1", latencyOptimizationLevel:int=0) -> tuple[bytes,str]:
        warn("This function is deprecated. Please use generate_audio_v2() instead, which supports the new options for the v2 models. See the porting guide on https://elevenlabslib.readthedocs.io for more information.", DeprecationWarning)

        return self.generate_audio_v2(prompt, GenerationOptions(model_id, latencyOptimizationLevel, stability, similarity_boost))

    def generate_audio_v2(self, prompt: str, generationOptions:GenerationOptions=None) -> tuple[bytes,str]:
        """
        Generates speech for the given prompt and returns the audio data as bytes of an mp3 file alongside the new historyID.

        Tip:
            If you would like to save the audio to disk or otherwise, you can use helpers.save_audio_bytes().

        Args:
            prompt: The prompt to generate speech for.
            generationOptions (GenerationOptions): Options for the audio generation such as the model to use and the voice settings.
        Returns:
            A tuple consisting of the bytes of the audio file and its historyID.

        Note:
            If using PCM as the output_format, the return audio bytes are a WAV.
        """
        if generationOptions is None:
            generationOptions = GenerationOptions()

        #Since we need the sample rate directly, make sure it's a real one.
        generationOptions = self.linkedUser.get_real_audio_format(generationOptions)

        payload = self._generate_payload(prompt, generationOptions)
        params = self._generate_parameters(generationOptions)

        requestFunction = lambda: _api_json("/text-to-speech/" + self._voiceID + "/stream", self._linkedUser.headers, jsonData=payload, params=params)
        generationID = f"{self.voiceID} - {prompt} - {time.time()}"
        response = _api_tts_with_concurrency(requestFunction, generationID, self._linkedUser.generation_queue)
        audioData = response.content

        if "pcm" in generationOptions.output_format:
            audioData = pcm_to_wav(audioData, int(generationOptions.output_format.lower().replace("pcm_","")))

        return audioData, response.headers["history-item-id"]



    def generate_play_audio(self, prompt:str, playInBackground:bool, portaudioDeviceID:Optional[int] = None,
                                stability:Optional[float]=None, similarity_boost:Optional[float]=None,
                                onPlaybackStart:Callable=lambda: None, onPlaybackEnd:Callable=lambda: None, model_id:str="eleven_monolingual_v1", latencyOptimizationLevel:int=0) -> tuple[bytes,str, sd.OutputStream]:

        warn("This function is deprecated. Please use generate_play_audio_v2() instead, which supports the new options for the v2 models. See the porting guide on https://elevenlabslib.readthedocs.io for more information.", DeprecationWarning)
        return self.generate_play_audio_v2(prompt, PlaybackOptions(playInBackground, portaudioDeviceID, onPlaybackStart, onPlaybackEnd), GenerationOptions(model_id, latencyOptimizationLevel, stability, similarity_boost))

    def generate_play_audio_v2(self, prompt:str, playbackOptions:PlaybackOptions, generationOptions:GenerationOptions=None) -> tuple[bytes,str, sd.OutputStream]:
        """
        Generate audio bytes from the given prompt and play them using sounddevice.

        Tip:
            This function downloads the entire file before playing it back, and even if playInBackground is set, it will halt execution until the file is downloaded.
            If you need faster response times and background downloading and playback, use generate_and_stream_audio_v2.

        Parameters:
            prompt (str): The text prompt to generate audio from.
            playbackOptions (PlaybackOptions): Options for the audio playback such as the device to use and whether to run in the background.
            generationOptions (GenerationOptions, optional): Options for the audio generation such as the model to use and the voice settings.


        Returns:
           A tuple consisting of the bytes of the audio file, its historyID and the sounddevice OutputStream, to allow you to pause/stop the playback early.

        Note:
            If using PCM as the output_format, the return audio bytes are a WAV.
        """
        if generationOptions is None:
            generationOptions = GenerationOptions()

        audioData, historyID = self.generate_audio_v2(prompt, generationOptions)
        outputStream = play_audio_bytes_v2(audioData, playbackOptions)

        return audioData, historyID, outputStream


    def generate_stream_audio(self, prompt:str, portaudioDeviceID:Optional[int] = None,
                                  stability:Optional[float]=None, similarity_boost:Optional[float]=None, streamInBackground=False,
                                  onPlaybackStart:Callable=lambda: None, onPlaybackEnd:Callable=lambda: None, model_id:str="eleven_monolingual_v1", latencyOptimizationLevel:int=0) -> tuple[
        str, Future[Any]]:
        warn("This function is deprecated. Please use generate_stream_audio_v2() instead, which supports the new options for the v2 models. See the porting guide on https://elevenlabslib.readthedocs.io for more information.", DeprecationWarning)
        generationOptions = GenerationOptions(model_id,latencyOptimizationLevel,stability,similarity_boost)
        playbackOptions = PlaybackOptions(streamInBackground,portaudioDeviceID,onPlaybackStart,onPlaybackEnd)
        return self.generate_stream_audio_v2(prompt, playbackOptions, generationOptions)

    def generate_stream_audio_v2(self, prompt:Union[str, Iterator[str]], playbackOptions:PlaybackOptions, generationOptions:GenerationOptions=None, websocketOptions:WebsocketOptions=None) -> tuple[str, Future[Any]]:
        """
        Generate audio bytes from the given prompt (or str iterator) and stream them using sounddevice.

        If the runInBackground option in PlaybackOptions is true, it will download the audio data in a separate thread, without pausing the main thread.

        Warning:
            Currently, when doing input streaming, the API does not return the history item ID. This function will therefore return None in those cases. I will fix it once it does.

        Parameters:
            prompt (str|Iterator[str]): The text prompt to generate audio from OR an iterator that returns multiple strings (for input streaming).
            playbackOptions (PlaybackOptions): Options for the audio playback such as the device to use and whether to run in the background.
            generationOptions (GenerationOptions, optional): Options for the audio generation such as the model to use and the voice settings.
            websocketOptions (WebsocketOptions, optional): Options for the websocket streaming. Ignored if not passed when not using websockets.

        Returns:
            A tuple consisting of the historyID for the newly created item and a future which will hold the audio OutputStream (to control playback)
        """
        if generationOptions is None:
            generationOptions = GenerationOptions()

        #We need the real sample rate.
        generationOptions = self.linkedUser.get_real_audio_format(generationOptions)

        if isinstance(prompt, str):
            payload = self._generate_payload(prompt, generationOptions)
            path = "/text-to-speech/" + self._voiceID + "/stream"
            #Not using input streaming
            params = self._generate_parameters(generationOptions)
            requestFunction = lambda: requests.post(apiEndpoint + path, headers=self._linkedUser.headers, json=payload, stream=True,
                                                    params = params, timeout=requests_timeout)
            generationID = f"{self.voiceID} - {prompt} - {time.time()}"
            responseConnection = _api_tts_with_concurrency(requestFunction, generationID, self._linkedUser.generation_queue)
        else:
            if websocketOptions is None:
                websocketOptions = WebsocketOptions()
            responseConnection = self._generate_websocket_connection(generationOptions, websocketOptions)
        if "mp3" in generationOptions.output_format:
            streamer = _Mp3Streamer(playbackOptions)
        else:
            streamer = _PCMStreamer(playbackOptions, int(generationOptions.output_format.lower().replace("pcm_", "")))
        audioStreamFuture = concurrent.futures.Future()

        if playbackOptions.runInBackground:
            mainThread = threading.Thread(target=streamer.begin_streaming, args=(responseConnection, audioStreamFuture, prompt))
            mainThread.start()
        else:
            streamer.begin_streaming(responseConnection, audioStreamFuture, prompt)
        if isinstance(responseConnection, requests.Response):
            return responseConnection.headers["history-item-id"], audioStreamFuture
        else:
            return "no_history_id_available", audioStreamFuture

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

    def play_preview(self, playInBackground:bool, portaudioDeviceID:Optional[int] = None,
                                onPlaybackStart:Callable=lambda: None, onPlaybackEnd:Callable=lambda: None) -> sd.OutputStream:
        warn("This function is deprecated. Use play_preview_v2 instead.", DeprecationWarning)
        return self.play_preview_v2(PlaybackOptions(playInBackground, portaudioDeviceID, onPlaybackStart, onPlaybackEnd))

    def play_preview_v2(self, playbackOptions:PlaybackOptions) -> sd.OutputStream:
        return play_audio_bytes_v2(self.get_preview_bytes(), playbackOptions)


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

    def set_sharing(self, sharingEnabled:bool) -> Union[str,None]:
        """
        Edits the sharing status, assuming it is not a copied voice.

        Args:
            sharingEnabled (bool): Whether to enable or disable sharing.

        Returns:
            str|None: The share URL for the voice, if you enabled sharing, or None if you disabled it.
        """
        warn("This is currently broken, as ElevenLabs have disabled accessing the sharing endpoints via the API key.")

        payload = {
            "enable":sharingEnabled,
            "emails":[]
        }
        sharingInfo = self.update_data()["sharing"]
        if sharingInfo is not None and sharingInfo["status"] == "copied":
            raise RuntimeError("Cannot change sharing status of copied voices!")

        response = _api_json("/voices/" + self._voiceID + "/share", self._linkedUser.headers, jsonData=payload)
        if sharingEnabled:
            return self.get_share_link()
        else:
            return None

    def set_library_sharing(self, sharingEnabled:bool) -> None:
        """
        Edits the library sharing status, assuming it is not a copied voice.

        Note:
            If you try to enable library sharing but don't have normal sharing enabled, it will be enabled automatically.

            The same does NOT apply in reverse - if you disable library sharing, normal sharing will remain enabled.

        Args:
            sharingEnabled (bool): Whether to enable or disable public library sharing.

        """
        sharingEnabledString = str(sharingEnabled).lower()
        sharingInfo = self.update_data()["sharing"]
        if sharingInfo is not None and sharingInfo["status"] == "copied":
            raise RuntimeError("Cannot change library sharing status of copied voices!")

        if sharingInfo is None or sharingInfo["status"] != "enabled" and sharingEnabled:
            self.set_sharing(sharingEnabled)

        response = _api_multipart("/voices/" + self._voiceID + "/share-library", self._linkedUser.headers, data=sharingEnabledString)

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

class _AudioStreamer:
    def __init__(self):
        self._events = dict()

    def _stream_downloader_function(self, streamedResponse: requests.Response):
        # This is the function running in the download thread.
        streamedResponse.raise_for_status()
        totalLength = 0
        logging.debug("Starting iter...")
        for chunk in streamedResponse.iter_content(chunk_size=_downloadChunkSize):
            self._stream_downloader_chunk_handler(chunk)
            totalLength += len(chunk)

        logging.debug("Download finished - " + str(totalLength) + ".")
        self._events["downloadDoneEvent"].set()
        return

    def _stream_downloader_function_websockets(self, websocket: websockets.sync.client.ClientConnection, textIterator: Iterator[str]):
        totalLength = 0
        logging.debug("Starting iter...")

        for text_chunk in _text_chunker(textIterator):
            data = dict(text=text_chunk, try_trigger_generation=True)
            try:
                websocket.send(json.dumps(data))
            except websockets.exceptions.ConnectionClosedError as e:
                logging.exception(f"Generation failed, shutting down: {e}")
                raise e

            try:
                data = json.loads(websocket.recv(1e-4))
                if data["audio"]:
                    chunk = base64.b64decode(data["audio"])
                    self._stream_downloader_chunk_handler(chunk)
                    totalLength += len(chunk)
            except TimeoutError as e:
                pass

        # Send end of stream
        websocket.send(json.dumps(dict(text="")))

        # Receive remaining audio
        while True:
            try:
                data = json.loads(websocket.recv())
                if data["audio"]:
                    chunk = base64.b64decode(data["audio"])
                    self._stream_downloader_chunk_handler(chunk)
                    totalLength += len(chunk)
            except websockets.exceptions.ConnectionClosed:
                break

        logging.debug("Download finished - " + str(totalLength) + ".")
        self._events["downloadDoneEvent"].set()

    def _stream_downloader_chunk_handler(self, chunk):
        pass


class _Mp3Streamer(_AudioStreamer):

    def __init__(self,playbackOptions:PlaybackOptions):
        super().__init__()
        self._dtype= "float32"
        self._q = queue.Queue()
        self._bytesFile = io.BytesIO()
        self._bytesSoundFile: Optional[BodgedSoundFile] = None  # Needs to be created later.
        self._bytesLock = threading.Lock()
        self._onPlaybackStart = playbackOptions.onPlaybackStart
        self._onPlaybackEnd = playbackOptions.onPlaybackEnd
        self._frameSize = 0

        self._deviceID = playbackOptions.portaudioDeviceID or sd.default.device

        self._events: dict[str, threading.Event] = {
            "playbackFinishedEvent": threading.Event(),
            "headerReadyEvent": threading.Event(),
            "soundFileReadyEvent": threading.Event(),
            "downloadDoneEvent": threading.Event(),
            "blockDataAvailable": threading.Event(),
            "playbackStartFired": threading.Event()
        }

    def _stream_downloader_function(self, streamedResponse: requests.Response):
        super()._stream_downloader_function(streamedResponse)
        self._events["blockDataAvailable"].set()    #This call only happens once the download is entirely complete.
        return

    def _stream_downloader_function_websockets(self, websocket: websockets.sync.client.ClientConnection, textIterator: Iterator[str]):
        super()._stream_downloader_function_websockets(websocket, textIterator)
        self._events["blockDataAvailable"].set()    #This call only happens once the download is entirely complete.

    def begin_streaming(self, streamConnection:Union[requests.Response, websockets.sync.client.ClientConnection], future:concurrent.futures.Future, text:Union[str,Iterator[str]]=None):
        # Clean all the buffers and reset all events.
        # Note: text is unused if it's not doing input_streaming - I just pass it anyway out of convenience.
        self._q = queue.Queue()
        self._bytesFile = io.BytesIO()
        self._bytesSoundFile: Optional[BodgedSoundFile] = None  # Needs to be created later.
        for eventName, event in self._events.items():
            event.clear()

        if isinstance(streamConnection, requests.Response):
            downloadThread = threading.Thread(target=self._stream_downloader_function, args=(streamConnection,))
        else:
            downloadThread = threading.Thread(target=self._stream_downloader_function_websockets, args=(streamConnection, text))
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
                data = self._get_data_from_download_thread()
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
                            if data != b"":
                                logging.debug("Still some data left, writing it...")
                                #logging.debug("Putting " + str(len(data)) +
                                #              " bytes in queue.")
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
                    logging.critical("...Read no data but the download isn't over? Panic. Just send silence.")
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
        self._bytesSoundFile = newSF
        logging.debug(f"Done recreating, now at {self._bytesSoundFile.tell()} (byte {self._bytesFile.tell()}).")

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
            readData = self._bytesSoundFile.buffer_read(dataToRead, dtype=dtype)    #Try to read the data
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
                    self._bytesSoundFile = newSF

                    preReadFramePos = self._bytesSoundFile.tell()
                    preReadBytesPos = self._bytesFile.tell()

                    try:
                        readData = self._bytesSoundFile.buffer_read(dataToRead, dtype=dtype)
                    except (AssertionError, soundfile.LibsndfileError):
                        readData = self._assertionerror_workaround(dataToRead, dtype, preReadFramePos, preReadBytesPos)
                    logging.debug("Now read " + str(len(readData)) +
                          " bytes. I sure hope that number isn't zero.")
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

class _PCMStreamer(_AudioStreamer):
    def __init__(self,playbackOptions:PlaybackOptions, samplerate:int):
        super().__init__()
        self._q = queue.Queue()
        self._onPlaybackStart = playbackOptions.onPlaybackStart
        self._onPlaybackEnd = playbackOptions.onPlaybackEnd
        self._dtype = "int16"
        self._samplerate = samplerate
        self._deviceID = playbackOptions.portaudioDeviceID or sd.default.device
        self._channels = 1
        self._events: dict[str, threading.Event] = {
            "playbackFinishedEvent": threading.Event(),
            "downloadDoneEvent": threading.Event(),
            "playbackStartFired": threading.Event(),
            "blockDataAvailable": threading.Event()
        }
        self._buffer = b""

    def _stream_downloader_function(self, streamedResponse:requests.Response):
        super()._stream_downloader_function(streamedResponse)
        self._stream_downloader_chunk_handler(b"")

    def _stream_downloader_function_websockets(self, websocket: websockets.sync.client.ClientConnection, textIterator: Iterator[str]):
        super()._stream_downloader_function_websockets(websocket, textIterator)
        self._stream_downloader_chunk_handler(b"")

    def begin_streaming(self, streamConnection:Union[requests.Response, websockets.sync.client.ClientConnection], future:concurrent.futures.Future, text:Union[str,Iterator[str]]=None):
        # Clean all the buffers and reset all events.
        # Note: text is unused if it's not doing input_streaming - I just pass it anyway out of convenience.
        self._q = queue.Queue()
        self._buffer = b""
        for eventName, event in self._events.items():
            event.clear()

        stream = sd.OutputStream(
            samplerate=self._samplerate, blocksize=_playbackBlockSize,
            device=self._deviceID, channels=self._channels, dtype=self._dtype,
            callback=self._stream_playback_callback, finished_callback=self._events["playbackFinishedEvent"].set)
        future.set_result(stream)
        logging.debug("Starting playback...")
        with stream:
            if isinstance(streamConnection, requests.Response):
                self._stream_downloader_function(streamConnection)
            else:
                self._stream_downloader_function_websockets(streamConnection, text)

            self._events["playbackFinishedEvent"].wait()  # Wait until playback is finished
            self._onPlaybackEnd()

        logging.debug("Stream done.")
        return

    def _stream_downloader_chunk_handler(self, chunk:bytes):
        #Split the code for easier handling
        self._buffer += chunk
        while len(self._buffer) >= _playbackBlockSize*2:    #*2 due to the audio frame size
            frame_data, self._buffer = self._buffer[:_playbackBlockSize*2], self._buffer[_playbackBlockSize*2:]
            audioData = numpy.frombuffer(frame_data, dtype=self._dtype)
            self._q.put(audioData.reshape(-1, self._channels))

        if self._events["downloadDoneEvent"].is_set() and len(self._buffer) > 0:
            logging.debug("Download is done, dump the remaining audio in the queue.")
            audioData = numpy.frombuffer(self._buffer, dtype=self._dtype)
            self._q.put(audioData.reshape(-1, self._channels))

    def _stream_playback_callback(self, outdata, frames, timeData, status):
        assert frames == _playbackBlockSize

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
