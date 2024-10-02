from __future__ import annotations

import concurrent.futures
from typing import Iterator, Dict
from typing import TYPE_CHECKING

import numpy
from websockets.sync.client import connect

if TYPE_CHECKING:
    from elevenlabslib.Sample import Sample
    from elevenlabslib.User import User

from elevenlabslib.helpers import *
from elevenlabslib.helpers import _api_json, _api_del, _api_get, _api_multipart, _api_tts_with_concurrency, _reformat_transcript, _NumpyMp3Streamer, _NumpyRAWStreamer, _NumpyPlaybacker, _pcm_to_wav, \
    _ulaw_to_wav


class Voice:
    """
    Represents a voice in the ElevenLabs API.

    It's the parent class for all voices, and used directly for the premade ones.
    """
    @staticmethod
    def voiceFactory(voiceData, linkedUser: User) -> Voice | EditableVoice | ClonedVoice | ProfessionalVoice:
        """
        Initializes a new instance of Voice or one of its subclasses depending on voiceData.

        Args:
            voiceData: A dictionary containing the voice data.
            linkedUser: An instance of the User class representing the linked user.

        Returns:
            Voice | DesignedVoice | ClonedVoice: The voice object
        """
        category = voiceData["category"]
        if category == "premade":
            return Voice(voiceData, linkedUser)
        elif category == "cloned":
            return ClonedVoice(voiceData, linkedUser)
        elif category == "generated":
            return DesignedVoice(voiceData, linkedUser)
        elif category == "professional":
            return ProfessionalVoice(voiceData, linkedUser)
        else:
            raise ValueError(f"{category} is not a valid voice category!")

    def __init__(self, voiceData, linkedUser:User):
        """
        Initializes a new instance of the Voice class.
        Don't use this constructor directly. Use the factory instead.

        Args:
            voiceData: A dictionary containing the voice data.
            linkedUser: An instance of the User class representing the linked user.
        """
        self._linkedUser = linkedUser

        self.name = voiceData["name"]
        self.description = voiceData["description"]
        self.voiceID = voiceData["voice_id"]
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
        response = _api_get("/voices/" + self.voiceID, self._linkedUser.headers, params={"with_settings": True})

        voiceData = response.json()
        self.name = voiceData["name"]
        self.description = voiceData["description"]
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
            User: The user linked to the voice.

        """
        return self._linkedUser

    @linkedUser.setter
    def linkedUser(self, newUser: User):
        """
        Set the user linked to the voice, whose API key will be used.

        Warning:
            Only supported for premade voices, as others do not have consistent IDs.

        Args:
            newUser (User): The new user to link to the voice.

        """
        if self.category != "premade":
            raise ValueError("Cannot change linked user of a non-premade voice.")
        self._linkedUser = newUser

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
        _api_json("/voices/" + self.voiceID + "/settings/edit", self._linkedUser.headers, jsonData=payload)
        self._settings = payload

    def _generate_payload_and_options(self, prompt:Union[str, bytes, BinaryIO], generation_options:GenerationOptions=None, stitching_options:StitchingOptions=None) -> (dict, GenerationOptions):
        """
        Generates the payload for the text-to-speech API call.

        Args:
            prompt (str|bytes): The prompt or audio to generate speech for.
            generation_options (GenerationOptions): The options for this generation.
            stitching_options (StitchingOptions): The stitching options for this generation.
        Returns:
            A tuple of:
            dict: A dictionary representing the payload for the API call.
            GenerationOptions: The generationOptions with the real values (including those taken from the stored settings)
        """

        generation_options = dataclasses.replace(generation_options)  #Ensure we have a copy, not the original.
        generation_options = self._complete_generation_options(generation_options)

        voice_settings = generation_options.get_voice_settings_dict()

        model_id = generation_options.model_id

        if isinstance(prompt, str):
            payload = {
                "model_id": model_id,
                "text": prompt,
                "seed": generation_options.seed,
                "language_code": generation_options.language_code
            }

            if stitching_options:
                payload["previous_text"] = stitching_options.previous_text
                if not stitching_options.auto_next_text:
                    payload["next_text"] = stitching_options.next_text
                else:
                    payload["next_text"] = emotion_prompts[get_emotion_for_prompt(prompt)]

                if stitching_options.previous_request_ids:
                    payload["previous_request_ids"] = stitching_options.previous_request_ids

                if stitching_options.next_request_ids:
                    payload["next_request_ids"] = stitching_options.next_request_ids

        else:
            if "sts" not in model_id:
                model_id = default_sts_model
            payload = {"model_id": model_id}

        if generation_options.pronunciation_dictionaries:
            payload["pronunciation_dictionary_locators"]:List[Dict[str, int]] = list()
            for dictionary in generation_options.pronunciation_dictionaries:
                payload["pronunciation_dictionary_locators"].append({
                    "pronunciation_dictionary_id": dictionary.pronunciation_dictionary_id,
                    "version_id": dictionary.version_id
                })



        if isinstance(prompt, str):
            payload["voice_settings"] = voice_settings
        else:
            payload["voice_settings"] = json.dumps(voice_settings)

        #Clean up empty values
        keys_to_pop = []
        for key, value in payload.items():
            if value is None:
                keys_to_pop.append(key)
        for key in keys_to_pop:
            payload.pop(key)

        return payload, generation_options

    def _complete_generation_options(self, generationOptions:GenerationOptions) -> GenerationOptions:
        generationOptions = self._linkedUser.get_real_audio_format(generationOptions)
        generationOptions = dataclasses.replace(generationOptions)
        for key, currentValue in self.settings.items():
            overriddenValue = getattr(generationOptions, key, None)
            if overriddenValue is None:
                setattr(generationOptions, key, currentValue)
        return generationOptions

    def _generate_parameters(self, generationOptions:GenerationOptions = None):
        params = dict()
        generationOptions = self.linkedUser.get_real_audio_format(generationOptions)
        params["optimize_streaming_latency"] = generationOptions.latencyOptimizationLevel
        params["output_format"] = generationOptions.output_format
        return params

    def _generate_websocket(self, websocketOptions:WebsocketOptions=None, generationOptions:GenerationOptions=None) -> websockets.sync.client.ClientConnection:
        """
        Generates a websocket connection for the input-streaming endpoint.

        Args:
            websocketOptions (WebsocketOptions): The settings for the websocket.
            generationOptions (GenerationOptions): The options for this generation (with all values, so make a copy and run self._complete_generation_options() on it first!)
        Returns:
            A tuple of:
            dict: A dictionary representing the payload for the API call.
            GenerationOptions: The generationOptions with the real values (including those taken from the stored settings)
        """
        voice_settings = self._complete_generation_options(generationOptions).get_voice_settings_dict()

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

        if generationOptions.language_code:
            websocketURL += f"&language_code={generationOptions.language_code}"

        websocket = connect(
            websocketURL,
            additional_headers=self.linkedUser.headers
        )
        websocket.send(json.dumps(BOS))

        return websocket

    def generate_audio_v3(self, prompt: Union[str,bytes, BinaryIO], generation_options:GenerationOptions=GenerationOptions(),
                          prompting_options:PromptingOptions=None, stitching_options:StitchingOptions=StitchingOptions()) -> \
            tuple[Future[bytes], Optional[Future[GenerationInfo]]]:
        """
        Generates speech for the given prompt or audio and returns the audio data as bytes of a file alongside the new historyID.

        Tip:
            If you would like to save the audio to disk or otherwise, you can use helpers.save_audio_bytes().

        Args:
            prompt (str|bytes|BinaryIO): The text prompt or audio bytes/file pointer to generate speech for.
            generation_options (GenerationOptions): Options for the audio generation such as the model to use and the voice settings.
            stitching_options (StitchingOptions, optional): Options for request stitching and pre/post text.
        Returns:
            tuple[Future[bytes], Optional[GenerationInfo]]:
                - A future that will contain the bytes of the audio file once the generation is complete.
                - An optional future that will contain the GenerationInfo object for the generation.

        Note:
            If using PCM as the output_format, the return audio bytes are a WAV.
        """
        generation_options = self.linkedUser.get_real_audio_format(generation_options)

        if prompting_options:
            warn("The prompting_options parameter is outdated and will be removed. Use stitching_options instead.", DeprecationWarning)
            stitching_options = prompting_options


        payload, generation_options = self._generate_payload_and_options(prompt, generation_options, stitching_options)
        params = self._generate_parameters(generation_options)
        if isinstance(prompt, str):
            generationID = f"{self.voiceID} - {prompt} - {time.time()}"
            requestFunction = lambda: _api_json("/text-to-speech/" + self.voiceID + "/with-timestamps", self._linkedUser.headers, jsonData=payload, params=params)
        else:
            if "output_format" in params:
                params.pop("output_format")

            source_audio, io_hash = io_hash_from_audio(prompt)
            files = {"audio": source_audio}
            generationID = f"{self.voiceID} - {io_hash} - {time.time()}"
            requestFunction = lambda: _api_multipart("/speech-to-speech/" + self.voiceID + "/stream",
                                                     self._linkedUser.headers, data=payload, params=params, filesData=files, stream=True)

        audio_future = concurrent.futures.Future()
        info_future = concurrent.futures.Future()

        def wrapped():
            responseConnection = _api_tts_with_concurrency(requestFunction, generationID, self._linkedUser.generation_queue)
            response_headers = responseConnection.headers
            responseData = responseConnection.content
            response_dict  = json.loads(responseData.decode("utf-8"))
            audioData = base64.b64decode(response_dict["audio_base64"])

            info_future.set_result(GenerationInfo(history_item_id=response_headers.get("history-item-id"),
                                            request_id=response_headers.get("request-id"),
                                            tts_latency_ms=response_headers.get("tts-latency-ms"),
                                            transcript=_reformat_transcript(response_dict['alignment']),
                                            character_cost=int(response_headers.get("character-cost", "-1"))))

            if "output_format" in params:
                if "pcm" in params["output_format"]:
                    audioData = _pcm_to_wav(audioData, int(params["output_format"].lower().replace("pcm_", "")))
                if "ulaw" in params["output_format"]:
                    audioData = _ulaw_to_wav(audioData, int(params["output_format"].lower().replace("ulaw_", "")))

            audio_future.set_result(audioData)

        threading.Thread(target=wrapped).start()

        return audio_future, info_future

    def _setup_streamer(self, prompt:Union[str, Iterator[str], Iterator[dict], bytes, BinaryIO],
                        generation_options:GenerationOptions=GenerationOptions(), websocket_options:WebsocketOptions=WebsocketOptions(),
                        stitching_options:StitchingOptions=StitchingOptions()) -> Union[_NumpyMp3Streamer, _NumpyRAWStreamer]:
        """
        Internal use only - sets up and returns a _NumpyStreamer of the correct type, which will stream the audio data.
        """
        # We need the real sample rate.
        generation_options = self._complete_generation_options(generation_options)

        response_connection_future = concurrent.futures.Future()
        if isinstance(prompt, str):
            payload, generation_options = self._generate_payload_and_options(prompt, generation_options, stitching_options)
            path = "/text-to-speech/" + self.voiceID + "/stream/with-timestamps"
            # Not using input streaming
            params = self._generate_parameters(generation_options)
            requestFunction = lambda: _api_json(path, headers=self._linkedUser.headers, jsonData=payload, stream=True, params=params)

            generationID = f"{self.voiceID} - {prompt} - {time.time()}"
            def wrapper():
                response_connection_future.set_result(_api_tts_with_concurrency(requestFunction, generationID, self._linkedUser.generation_queue))
            threading.Thread(target=wrapper).start()

        elif isinstance(prompt, io.IOBase) or isinstance(prompt, bytes):
            payload, generation_options = self._generate_payload_and_options(prompt, generation_options, stitching_options)
            path = "/speech-to-speech/" + self.voiceID + "/stream"
            # Using speech to speech
            params = self._generate_parameters(generation_options)
            if "output_format" in params:
                params.pop("output_format")

            source_audio, audio_hash = io_hash_from_audio(prompt)

            files = {"audio": source_audio}

            requestFunction = lambda: _api_multipart(path, headers=self._linkedUser.headers, data=payload, stream=True, filesData=files, params=params)
            generationID = f"{self.voiceID} - {audio_hash} - {time.time()}"
            def wrapper():
                response_connection_future.set_result(_api_tts_with_concurrency(requestFunction, generationID, self._linkedUser.generation_queue))
            threading.Thread(target=wrapper).start()

        elif isinstance(prompt, Iterator) or inspect.isasyncgen(prompt):
            if inspect.isasyncgen(prompt):
                prompt = SyncIterator(prompt)

            def wrapper():
                response_connection_future.set_result(self._generate_websocket(websocket_options, generation_options))
            threading.Thread(target=wrapper).start()
        else:
            raise ValueError("Unknown type passed for prompt.")

        streamer: Union[_NumpyMp3Streamer, _NumpyRAWStreamer]

        if "mp3" in generation_options.output_format or isinstance(prompt, io.IOBase) or isinstance(prompt, bytes):
            streamer = _NumpyMp3Streamer(response_connection_future, generation_options, websocket_options, prompt)
        else:
            streamer = _NumpyRAWStreamer(response_connection_future, generation_options, websocket_options, prompt)

        return streamer

    def stream_audio_v3(self,
                        prompt:Union[str, Iterator[str], Iterator[dict], AsyncIterator, bytes, BinaryIO],
                        playback_options:PlaybackOptions=PlaybackOptions(),
                        generation_options:GenerationOptions=GenerationOptions(),
                        websocket_options:WebsocketOptions=WebsocketOptions(),
                        prompting_options:PromptingOptions=None,
                        stitching_options:StitchingOptions=StitchingOptions(),
                        disable_playback:bool = False
                        ) -> tuple[queue.Queue[numpy.ndarray], Optional[queue.Queue[str]], Optional[Future[sounddevice.OutputStream]], Optional[Future[GenerationInfo]]]:
        """
        Generate and stream audio from the given prompt (or str iterator).

        Parameters:
            prompt (str|Iterator[str]|Iterator[dict]|bytes|BinaryIO): The text prompt to generate audio from OR an iterator that returns multiple strings or dicts (for input streaming) OR the bytes/file pointer of an audio file.
            playback_options (PlaybackOptions, optional): Options for the audio playback such as the device to use and whether to run in the background.
            generation_options (GenerationOptions, optional): Options for the audio generation such as the model to use and the voice settings.
            websocket_options (WebsocketOptions, optional): Options for the websocket streaming. Ignored if not passed when not using websockets.
            stitching_options (StitchingOptions, optional): Options for request stitching and pre/post prompting the audio.
            disable_playback (bool, optional): Allows you to disable playback altogether.
        Returns:
            tuple[queue.Queue[numpy.ndarray], Optional[queue.Queue[str]], Optional[Future[OutputStream]], Optional[GenerationInfo]]:
                - A queue containing the numpy audio data as float32 arrays.
                - An queue for audio transcripts.
                - An optional future for controlling the playback, returned if playback is not disabled.
                - An optional future containing a GenerationInfo with metadata about the audio generation.
        """

        generation_options = self._complete_generation_options(generation_options)

        if prompting_options:
            warn("The prompting_options parameter is outdated and will be removed. Use stitching_options instead.", DeprecationWarning)
            stitching_options = prompting_options

        streamer: Union[_NumpyMp3Streamer, _NumpyRAWStreamer] = self._setup_streamer(prompt, generation_options, websocket_options, stitching_options)
        audio_stream_future, transcript_queue, generation_info_future = None, None, None

        if disable_playback:
            mainThread = threading.Thread(target=streamer.begin_streaming)
            mainThread.start()
        else:
            audio_stream_future = concurrent.futures.Future()

            player = _NumpyPlaybacker(streamer.playback_queue, playback_options, generation_options)
            threading.Thread(target=streamer.begin_streaming).start()

            if playback_options.runInBackground:
                playback_thread = threading.Thread(target=player.begin_playback, args=(audio_stream_future,))
                playback_thread.start()
            else:
                player.begin_playback(audio_stream_future)

        if isinstance(prompt, str) or isinstance(prompt, io.IOBase) or isinstance(prompt, bytes):
            generation_info_future = concurrent.futures.Future()
            def wrapper():
                connection_headers = streamer.connection_future.result().headers
                generation_info_future.set_result(GenerationInfo(history_item_id=connection_headers.get("history-item-id"),
                               request_id=connection_headers.get("request-id"),
                               tts_latency_ms=connection_headers.get("tts-latency-ms"),
                               character_cost=int(connection_headers.get("character-cost", "-1"))))
            threading.Thread(target=wrapper).start()
            if isinstance(prompt, str):
                transcript_queue = streamer.transcript_queue
        else:
            transcript_queue = streamer.transcript_queue

        return streamer.userfacing_queue, transcript_queue, audio_stream_future, generation_info_future

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


class EditableVoice(Voice):
    """
    This class is shared by all the voices which can have their details edited and be deleted from an account.
    """
    def __init__(self, voiceData, linkedUser: User):
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
        _api_multipart("/voices/" + self.voiceID + "/edit", self._linkedUser.headers, data=payload)
    def delete_voice(self):
        """
        This function deletes the voice, and also sets the voiceID to be empty.
        """
        if self._category == "premade":
            raise RuntimeError("Cannot delete premade voices!")
        response = _api_del("/voices/" + self.voiceID, self._linkedUser.headers)
        self.voiceID = ""

class DesignedVoice(EditableVoice):
    """
    Represents a voice created via voice design.
    """
    def __init__(self, voiceData, linkedUser: User):
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

        return f"https://elevenlabs.io/voice-lab/share/{publicOwnerID}/{originalVoiceID}"

class ProfessionalVoice(EditableVoice):
    """
    Represents a voice created via professional voice cloning.
    """
    def __init__(self, voiceData, linkedUser: User):
        super().__init__(voiceData, linkedUser)

    def get_samples(self) -> list[Sample]:
        """
        Caution:
            There is an API bug here. The /voices/voiceID endpoint does not correctly return sample data for professional cloning voices.

        Returns:
            list[Sample]: The samples that make up this professional voice clone.
        """
        outputList = list()
        samplesData = self.update_data()["samples"]
        from elevenlabslib.Sample import Sample
        for sampleData in samplesData:
            outputList.append(Sample(sampleData, self))
        return outputList

    def get_high_quality_models(self) -> list[Model]:
        return [model for model in self.linkedUser.get_models() if model.modelID in self.update_data()["high_quality_base_model_ids"]]

class ClonedVoice(EditableVoice):
    """
    Represents a voice created via instant voice cloning.
    """
    def __init__(self, voiceData, linkedUser: User):
        super().__init__(voiceData, linkedUser)

    def get_samples(self) -> list[Sample]:
        """
        Returns:
            list[Sample]: The samples that make up this voice clone.
        """

        outputList = list()
        samplesData = self.update_data()["samples"]
        from elevenlabslib.Sample import Sample
        for sampleData in samplesData:
            outputList.append(Sample(sampleData, self))
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

        _api_multipart("/voices/" + self.voiceID + "/edit", self._linkedUser.headers, data=payload, filesData=files)

class LibraryVoiceData:
    def __init__(self, lib_voice_data):
        # Core properties
        self.share_link = f"https://elevenlabs.io/voice-lab/share/{lib_voice_data.get('public_owner_id')}/{lib_voice_data.get('voice_id')}"
        self.name = lib_voice_data.get('name')
        self.description = lib_voice_data.get('description')

        # Speaker information
        self.speaker_info = LibVoiceInfo(
            category=LibCategory(lib_voice_data.get('category')),
            gender=LibGender(lib_voice_data.get('gender')),
            age=LibAge(lib_voice_data.get('age')),
            accent=LibAccent(lib_voice_data.get('accent')),
            language=lib_voice_data.get('language'),
        )

        # Usage information
        self.usage_info = {
            'free_users_allowed': lib_voice_data.get('free_users_allowed'),
            'live_moderation_enabled': lib_voice_data.get('live_moderation_enabled'),
            'notice_period': lib_voice_data.get('notice_period'),
            'use_case': lib_voice_data.get('use_case'),
            'rate': lib_voice_data.get('rate'),
        }

        # Library information
        self.library_info = {
            'cloned_by_count': lib_voice_data.get('cloned_by_count'),
            'date_unix': lib_voice_data.get('date_unix'),
            'descriptive': lib_voice_data.get('descriptive'),  # Assuming this is a detailed description or tags
            'usage_character_count_1y': lib_voice_data.get('usage_character_count_1y'),
            'usage_character_count_7d': lib_voice_data.get('usage_character_count_7d'),
            'preview_url': lib_voice_data.get('preview_url'),
            'public_owner_id': lib_voice_data.get('public_owner_id'),
            'voice_id': lib_voice_data.get('voice_id')
        }

        # Social media information
        self.social_media = {
            'instagram': lib_voice_data.get('instagram_username'),
            'tiktok': lib_voice_data.get('tiktok_username'),
            'twitter': lib_voice_data.get('twitter_username'),
            'youtube': lib_voice_data.get('youtube_username'),
        }

        # Metadata for less frequently accessed or auxiliary information
        self.all_metadata = lib_voice_data

