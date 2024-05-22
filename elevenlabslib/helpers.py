from __future__ import annotations

import asyncio
import concurrent.futures
from concurrent.futures import Future
import dataclasses
import inspect
import io
from enum import Enum
import logging
import queue
import threading
import time
import zlib
from typing import Optional, BinaryIO, Callable, Union, Any, Iterator, List, AsyncIterator, Tuple, TYPE_CHECKING, TextIO
from warnings import warn
import json
import numpy
import numpy as np
import sounddevice
import sounddevice as sd
import soundfile
import soundfile as sf
import requests
import os

from typing import TYPE_CHECKING

import websockets.sync.client
if TYPE_CHECKING:
    from elevenlabslib import Voice
    from elevenlabslib.Model import Model
from elevenlabslib._audio_cutter_helper import split_audio


api_endpoint = "https://api.elevenlabs.io/v1"
default_headers = {'accept': '*/*'}
requests_timeout = 900

#FYI, "pro" = "independent_publisher"
subscription_tiers = ["free", "starter", "creator", "pro", "growing_business", "enterprise"]


#camelCase vars for compatibility
subscriptionTiers = subscription_tiers
defaultHeaders = default_headers
apiEndpoint = api_endpoint

default_sts_model = "eleven_multilingual_sts_v2"

category_shorthands = {
    "generated": "gen",
    "professional": "pvc",
    "cloned": "ivc",
    "premade": "pre",
}
model_shorthands = {
    "eleven_multilingual_v2":"m2",
    "eleven_english_v2": "e2",
    "eleven_multilingual_v1": "m1",
    "eleven_monolingual_v1": "e1",
    "eleven_turbo_v2": "t2"
}

class LibCategory(Enum):
    PROFESSIONAL = "professional"
    VOICE_DESIGN = "generated"
    NONE = None

    def _missing_(self, value=None):
        return LibCategory.NONE


class LibGender(Enum):
    MALE = "male"
    FEMALE = "female"
    NEUTRAL = "neutral"
    NONE = None

    def _missing_(self, value=None):
        return LibGender.NONE

class LibAge(Enum):
    YOUNG = "young"
    MIDDLE_AGED = "middle_aged"
    OLD = "old"
    NONE = None

    def _missing_(self, value=None):
        return LibAge.NONE

class LibAccent(Enum):
    BRITISH = "british"
    AMERICAN = "american"
    AFRICAN = "african"
    AUSTRALIAN = "australian"
    INDIAN = "indian"
    NONE = None

    def _missing_(self, value=None):
        return LibAccent.NONE

class LibVoiceInfo:
    """
    Contains the information for a voice in the Voice Library.
    """
    def __init__(self, category: LibCategory = None, gender: LibGender = None, age: LibAge = None, accent: LibAccent = None, language: str = None):
        """
        Initializes an instance.

        Parameters:
            category (LibCategory, optional): Whether the voice is generated or a professional clone
            gender (LibGender, optional): The gender of the voice
            age (LibAge, optional): The age of the voice
            accent (LibAccent, optional): The accent of the voice
            language (str, optional): The language of the voice, as a language code.
        """
        self.category = category
        self.gender = gender
        self.age = age
        self.accent = accent
        self.language = language

    def to_query_params(self):
        """
        Converts filter attributes to a dictionary of query parameters, omitting None values.
        """
        params = {
            'category': self.category.value if self.category else None,
            'gender': self.gender.value if self.gender else None,
            'age': self.age.value if self.age else None,
            'accent': self.accent.value if self.accent else None,
            'language': self.language,
        }
        # Filter out None values
        return {k: v for k, v in params.items() if v is not None}

class LibSort(Enum):
    TRENDING = "usage_character_count_7d"
    LATEST = "created_date"
    MOST_USERS = "cloned_by_count"
    MOST_CHARACTERS_GENERATED = "usage_character_count_1y"

def _api_call_v2(requestMethod, argsDict) -> requests.Response:
    path = argsDict["path"]
    if path[0] != "/":
        path = "/"+path
    argsDict["url"] = api_endpoint + path
    argsDict["timeout"] = requests_timeout
    argsDict.pop("path")

    response:requests.Response = requestMethod(**argsDict)
    try:
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        _pretty_print_POST(response)
        raise e

def _api_get(path, headers, stream=False, params=None) -> requests.Response:
    args = {
        "path":path,
        "headers":headers,
        "stream":stream
    }
    if params is not None:
        args["params"] = params
    return _api_call_v2(requests.get, args)
def _api_del(path, headers) -> requests.Response:
    args = {
        "path": path,
        "headers": headers
    }
    return _api_call_v2(requests.delete, args)
def _api_json(path, headers, jsonData, stream=False, params=None) -> requests.Response:
    args = {
        "path":path,
        "headers":headers,
        "json":jsonData,
        "stream":stream
    }
    if params is not None:
        args["params"] = params
    return _api_call_v2(requests.post, args)

def _api_multipart(path, headers, data, filesData=None, stream=False, params=None) -> requests.Response:
    args = {
        "path":path,
        "headers":headers,
        "stream":stream,
        "data":data
    }
    if filesData is not None:
        if isinstance(filesData, dict):
            for file in filesData.values():
                if isinstance(file, io.IOBase):
                    file.seek(0)    #Ensure we always read from the start

        args["files"] = filesData
    if params is not None:
        args["params"] = params

    return _api_call_v2(requests.post, args)

def _pretty_print_POST(res:requests.Response):
    req = res.request
    import logging
    logging.basicConfig(level=logging.DEBUG)
    logging.debug(f"RESPONSE DATA: {res.text}")
    logging.debug('REQUEST THAT CAUSED THE ERROR:\n{}\n{}\r\n{}\r\n\r\n{}'.format(
        '-----------START-----------',
        req.method + ' ' + req.url,
        '\r\n'.join('{}: {}'.format(k, v) for k, v in req.headers.items()),
        req.body,
    ))

@dataclasses.dataclass
class PlaybackOptions:
    """
    This class holds the options for playback.

    Parameters:
        runInBackground (bool, optional): Whether to play/stream audio in the background or wait for it to finish playing. Defaults to False.
        portaudioDeviceID (int, optional): The ID of the audio device to use for playback. Defaults to the default output device.
        onPlaybackStart (Callable, optional): Function to call once the playback begins.
        onPlaybackEnd (Callable, optional): Function to call once the playback ends.
        audioPostProcessor (Callable, optional): Function to apply post-processing to the audio. Must take a float32 ndarray (of arbitrary length) and an int (the sample rate) as input and return another float32 ndarray.
    """
    runInBackground: bool = False
    portaudioDeviceID: Optional[int] = None
    onPlaybackStart: Callable[[], Any] = lambda: None
    onPlaybackEnd: Callable[[], Any] = lambda: None
    audioPostProcessor: Callable[[np.ndarray, int], np.ndarray] = lambda x, y : x

@dataclasses.dataclass
class GenerationOptions:
    """
    This class holds the options for TTS generation.
    If any option besides model_id and latencyOptimizationLevel is omitted, the stored value associated with the voice is used.

    Parameters:
        model (Model|str, optional): The TTS model (or its ID) to use for the generation. Defaults to monolingual english v1.
        latencyOptimizationLevel (int, optional): The level of latency optimization (0-4) to apply. Defaults to 0.
        stability (float, optional): A float between 0 and 1 representing the stability of the generated audio. If omitted, the current stability setting is used.
        similarity_boost (float, optional): A float between 0 and 1 representing the similarity boost of the generated audio. If omitted, the current similarity boost setting is used.
        style (float, optional): A float between 0 and 1 representing how much focus should be placed on the text vs the associated audio data for the voice's style, with 0 being all text and 1 being all audio.
        use_speaker_boost (bool, optional): Boost the similarity of the synthesized speech and the voice at the cost of some generation speed.
        output_format (str, optional): Output format for the audio. mp3_highest and pcm_highest will automatically use the highest quality of that format you have available.
        forced_pronunciations (dict, optional): A dict specifying custom pronunciations for words. The key is the word, with the 'alphabet' and 'pronunciation' values required. This will replace it in the prompt directly.
    Note:
        The latencyOptimizationLevel ranges from 0 to 4. Each level trades off some more quality for speed.

        Level 4 might also mispronounce numbers/dates.

    Warning:
        The style and use_speaker_boost parameters are only available on v2 models, and will be ignored for v1 models.

        Setting style to higher than 0 and enabling use_speaker_boost will both increase latency.

        output_format is currently ignored when using speech to speech.

    Warning:
        Using pcm_highest and mp3_highest will cache the resulting quality for the user object. You can use user.update_audio_quality() to force an update.
    """
    model_id: Optional[str] = dataclasses.field(default=None, init=True, repr=False)
    latencyOptimizationLevel: int = 0
    stability: Optional[float] = None
    similarity_boost: Optional[float] = None
    style: Optional[float] = None
    use_speaker_boost: Optional[bool] = None
    model: Optional[Union[Model, str]] = "eleven_monolingual_v1"
    output_format:str = "mp3_highest"
    forced_pronunciations:Optional[dict] = None

    def __post_init__(self):
        if self.model_id:
            self.model = self.model_id
        if not self.model_id:
            if isinstance(self.model, str):
                self.model_id = self.model
            else:
                self.model_id = self.model.modelID

        #Validate values
        if self.forced_pronunciations:
            valid_alphabets =  ["ipa","cmu-arpabet"]
            for key, value in self.forced_pronunciations.items():
                if not isinstance(value, dict) or "alphabet" not in value or "pronunciation" not in value:
                    raise ValueError(f"Please ensure that each value in custom_pronunciations is a dict containing 'alphabet' and 'pronunciation' values (Error raised due to {key}).")
                value["alphabet"] = value["alphabet"].lower()
                if value["alphabet"] not in valid_alphabets:
                    raise ValueError(f"Please specify a valid alphabet for {key}. Valid values are: {valid_alphabets}")
        for var in [self.stability, self.similarity_boost, self.style]:
            if var is not None and (var < 0 or var > 1):
                raise ValueError("Please provide a value between 0 and 1 for stability, similarity_boost, and style.")

        if (self.latencyOptimizationLevel < 0 or self.latencyOptimizationLevel > 4) and self.latencyOptimizationLevel != -99:
            raise ValueError("Please provide a value between 0 and 4 for latencyOptimizationLevel")

        validOutputFormats = ["mp3_44100_64", "mp3_44100_96", "mp3_44100_128","mp3_44100_192", "pcm_16000", "pcm_22050", "pcm_24000", "pcm_44100", "mp3_highest","pcm_highest", "ulaw_8000"]

        if self.output_format not in validOutputFormats:
            raise ValueError("Selected output format is not valid.")

    def get_voice_settings_dict(self) -> dict:
        return {
            "similarity_boost":self.similarity_boost,
            "stability":self.stability,
            "style":self.style,
            "use_speaker_boost":self.use_speaker_boost
        }

def apply_pronunciations(text:str, generation_options:GenerationOptions) -> str:
    supported_models = ["eleven_monolingual_v1", "eleven_turbo_v2"]
    if generation_options.model_id not in supported_models:
        return text

    if generation_options.forced_pronunciations:
        for word, value in generation_options.forced_pronunciations.items():
            constructed_string = f'<phoneme alphabet="{value["alphabet"]}" ph="{value["pronunciation"]}">{word}</phoneme>'
            text = text.replace(word, constructed_string)

    return text

@dataclasses.dataclass
class WebsocketOptions:
    """
    This class holds the options for the websocket endpoint.

    Parameters:
        chunk_length_schedule (list[int], optional): Chunking schedule for generation. If you pass [50, 120, 500], the first audio chunk will be generated after recieving 50 characters, the second after 120 more (so 170 total), and the third onwards after 500. Defaults to [50], so always generating ASAP.
        try_trigger_generation (bool, optional): Whether to try and generate a chunk of audio at >50 characters, regardless of the chunk_length_schedule. Defaults to False, sent with every message (but can be overridden).
        enable_ssml_parsing (bool, optional): Whether to enable parsing of SSML tags, such as breaks or pronunciations. Increases latency. Defaults to False.
        buffer_char_length (int, optional): If the generation will be slower than realtime (using multilingual v2, for example) the library will buffer and wait to begin playback to ensure that there is no stuttering. Use this to override the amount of buffering. -1 means it will use the default (which is a safe, high value).
    """
    try_trigger_generation: bool = False
    chunk_length_schedule: List[int] = dataclasses.field(default_factory=lambda: [125])
    enable_ssml_parsing: bool = False
    buffer_char_length: int = -1

    def __post_init__(self):
        for value in self.chunk_length_schedule:
            if not(50 <= value <= 500):
                raise ValueError("Chunk length outside the [50,500] range.")

@dataclasses.dataclass
class PromptingOptions:
    """
    This class holds the options for pre/post-prompting the audio, to add emotion.

    Parameters:
        pre_prompt (str, optional): Prompt which will be place before the quoted text.
        post_prompt (str, optional): Prompt which will be placed after the quoted text.
        open_quote_duration_multiplier (float, optional): Multiplier indicating how much of the opening quote will be spoken (Between 0 and 1). Defaults to 0.70 if a pre-prompt is present to avoid bleedover.
        close_quote_duration_multiplier (float, optional): Multiplier for the duration of the closing quote (Between 0 and 1). Defaults to 0.70 if a post-prompt is present to avoid bleedover.
    """
    pre_prompt:str = ""
    post_prompt:str = ""
    open_quote_duration_multiplier: Optional[float] = None
    close_quote_duration_multiplier:Optional[float] = None

    def __post_init__(self):
        if "\"" in self.pre_prompt or "\"" in self.post_prompt:
            raise ValueError("Please do not include any quotes (\") in the post/pre-prompt.")
        if self.close_quote_duration_multiplier is None:
            if self.post_prompt != "":
                self.close_quote_duration_multiplier = 0.50
            else:
                self.close_quote_duration_multiplier = 1

        if self.open_quote_duration_multiplier is None:
            if self.pre_prompt != "":
                self.open_quote_duration_multiplier = 0.50
            else:
                self.open_quote_duration_multiplier = 1
        elif self.close_quote_duration_multiplier > 1:
            raise ValueError("Please input a valid value for last_character_duration_multiplier (between 0 and 1).")

@dataclasses.dataclass
class GenerationInfo:
    """
    This contains the information returned regarding a (non-websocket) generation.
    """
    history_item_id: Optional[str] = None
    request_id: Optional[str] = None
    tts_latency_ms: Optional[str] = None
    transcript: Optional[list[str]] = None

class Synthesizer:
    """
    This is a helper class, which allows you to queue up multiple audio generations.

    They will all be downloaded together, and will play back in the same order you put them in. I've found this gives the lowest possible latency.
    """
    def __init__(self, defaultPlaybackOptions:PlaybackOptions=PlaybackOptions(runInBackground=True),
                 defaultGenerationOptions:GenerationOptions=GenerationOptions(latencyOptimizationLevel=3),
                 defaultPromptingOptions:PromptingOptions=None):
        """
        Initializes the Synthesizer instance.
        Parameters:
            defaultPlaybackOptions (PlaybackOptions, optional): The default playback options (for the onPlayback callbacks), that will be used if none are specified when calling add_to_queue
            defaultGenerationOptions (GenerationOptions, optional): The default generation options, that will be used if none are specified when calling add_to_queue
            defaultGenerationOptions (PromptingOptions, optional): The default prompting options, that will be used if none are specified when calling add_to_queue
        """

        self._eventStreamQueue = queue.Queue()
        self._readyForPlaybackEvent = threading.Event()
        self._readyForPlaybackEvent.set()
        self._ttsQueue = queue.Queue()
        self._interruptEvent = threading.Event()
        self._currentStream: sd.OutputStream = None
        self._defaultGenOptions = defaultGenerationOptions
        self._defaultPromptOptions = defaultPromptingOptions
        if isinstance(defaultPlaybackOptions, int):
            logging.warning("Synthesizer no longer takes portAudioDeviceID as a parameter, please use defaultPlaybackOptions from now on. Wrapping it...")
            defaultPlaybackOptions = PlaybackOptions(runInBackground=True, portaudioDeviceID=defaultPlaybackOptions)
        self._defaultPlayOptions = defaultPlaybackOptions

    def start(self):
        """
        Begins processing the queued audio.
        """
        if self._interruptEvent.is_set():
            raise ValueError("Please do not re-use a stopped Synthesizer instance. Create a new one instead.")

        threading.Thread(target=self._ordering_thread).start() # Starts the thread that handles playback ordering.
        threading.Thread(target=self._consumer_thread).start() # Starts the consumer thread

    def stop(self):
        """
        Stops playing back audio once the current one is finished.
        """
        self._interruptEvent.set()

    def abort(self):
        """
        Stops playing back audio immediately.
        """
        self.stop()
        if self._currentStream is not None:
            self._currentStream.stop()

    def change_output_device(self, portAudioDeviceID:int):
        """
        Allows you to change the current output device.
        """
        warn("This is deprecated, use change_default_settings to change it through the defaultPlaybackOptions instead.", DeprecationWarning)
        self._defaultPlayOptions.portaudioDeviceID = portAudioDeviceID

    def change_default_settings(self, defaultGenerationOptions:GenerationOptions=None, defaultPlaybackOptions:PlaybackOptions=None, defaultPromptingOptions:PromptingOptions=None):
        """
        Allows you to change the default settings.
        """
        if defaultGenerationOptions is not None:
            self._defaultGenOptions = defaultGenerationOptions
        if defaultPlaybackOptions is not None:
            self._defaultPlayOptions = defaultPlaybackOptions
        if defaultPromptingOptions is not None:
            self._defaultPromptOptions = defaultPromptingOptions

    def add_to_queue(self, voice:Voice, prompt:str, generationOptions:GenerationOptions=None, playbackOptions:PlaybackOptions = None, promptingOptions:PromptingOptions=None) -> None:
        """
        Adds an item to the synthesizer queue.
        Parameters:
            voice (Voice): The voice that will speak the prompt
            prompt (str): The prompt to be spoken
            generationOptions (GenerationOptions, optional): Overrides the generation options for this generation
            playbackOptions (PlaybackOptions, optional): Overrides the playback options for this generation
            promptingOptions (PromptingOptions): Overrides the prompting options for this generation
        """
        if generationOptions is None:
            generationOptions = self._defaultGenOptions
        if playbackOptions is None:
            playbackOptions = self._defaultPlayOptions
        if promptingOptions is None:
            promptingOptions = self._defaultPromptOptions
        self._ttsQueue.put((voice, prompt, generationOptions, playbackOptions, promptingOptions))

    def _consumer_thread(self):
        voice, prompt, genOptions, playOptions = None, None, None, None
        while not self._interruptEvent.is_set():
            try:
                voice, prompt, genOptions, playOptions, promptOptions = self._ttsQueue.get(timeout=10)
                playOptions = dataclasses.replace(playOptions, runInBackground=True) #Ensure this is set to true, always.
            except queue.Empty:
                continue
            finally:
                if self._interruptEvent.is_set():
                    logging.debug("Synthetizer consumer loop exiting...")
                    return

            logging.debug(f"Synthesizing prompt: {prompt}")
            self._generate_events_and_begin(voice, prompt, genOptions, playOptions, promptOptions)

    def _generate_events_and_begin(self, voice:Voice, prompt:str, generationOptions:GenerationOptions, playbackOptions:PlaybackOptions, promptingOptions:PromptingOptions):
        newEvent = threading.Event()

        def startcallbackfunc():
            newEvent.wait()
            if self._interruptEvent.is_set():
                raise sounddevice.CallbackAbort
            playbackOptions.onPlaybackStart()
        def endcallbackfunc():
            playbackOptions.onPlaybackEnd()
            self._readyForPlaybackEvent.set()

        wrapped_playbackOptions = PlaybackOptions(runInBackground=True, portaudioDeviceID=playbackOptions.portaudioDeviceID, onPlaybackStart=startcallbackfunc, onPlaybackEnd=endcallbackfunc)

        _, streamFuture, _ = voice.generate_stream_audio_v2(prompt=prompt, generationOptions=generationOptions, playbackOptions=wrapped_playbackOptions, promptingOptions=promptingOptions)
        self._eventStreamQueue.put((newEvent, streamFuture))

    def _ordering_thread(self):
        nextEvent, nextStreamFuture = None, None
        while not self._interruptEvent.is_set():
            self._readyForPlaybackEvent.wait()
            self._readyForPlaybackEvent.clear()
            while not self._interruptEvent.is_set():
                try:
                    nextEvent, nextStreamFuture = self._eventStreamQueue.get(timeout=10)
                except queue.Empty:
                    continue
                finally:
                    if self._interruptEvent.is_set():
                        logging.debug("Synthetizer playback loop exiting...")
                        break
                nextEvent.set()
                self._currentStream = nextStreamFuture.result()
                break
        while True:
            try:
                nextEvent, nextStreamFuture = self._eventStreamQueue.get_nowait()
            except queue.Empty:
                break
            nextEvent.set() #Just set all of them so they exit.

class ReusableInputStreamer:
    """
    This is basically a reusable wrapper around a websocket connection.
    """
    def __init__(self, voice:Voice,
                 defaultPlaybackOptions:PlaybackOptions=PlaybackOptions(runInBackground=True),
                 generationOptions:GenerationOptions=GenerationOptions(latencyOptimizationLevel=3),
                 websocketOptions:WebsocketOptions=WebsocketOptions()
                 ):
        self._voice = voice
        self._websocket_ready_event = threading.Event()
        self._generationOptions = generationOptions
        self._defaultPlayOptions = defaultPlaybackOptions
        self._interruptEvent = threading.Event()
        self._currentStream: sd.OutputStream = None
        self._websocket: websockets.sync.client.ClientConnection = None
        self._websocketOptions = websocketOptions
        self._currentGenOptions: GenerationOptions = None   #These are the options tied to the current voice.
        self._last_renewal_time = 0
        self._ping_thread = threading.Thread(target=self._ping_function)
        self._iterator_queue = queue.Queue()

        self._renew_socket()
        self._ping_thread.start()
        threading.Thread(target=self._consumer_thread).start()  # Starts the consumer thread

    def change_voice(self, voice:Voice):
        self._voice = voice
        self._renew_socket()
    def stop(self):
        """
        Stops playing back audio once the current one is finished.
        """
        self._interruptEvent.set()

    def abort(self):
        """
        Stops playing back audio immediately.
        """
        self.stop()
        if self._currentStream is not None:
            self._currentStream.stop()
        if self._websocket is not None:
            self._websocket.close_socket()
    def change_settings(self, generationOptions:GenerationOptions=None, defaultPlaybackOptions:PlaybackOptions=None, websocketOptions:WebsocketOptions=None):
        """
        Allows you to change the settings and then re-establishes the socket.
        """
        if generationOptions is not None:
            self._generationOptions = generationOptions

        if defaultPlaybackOptions is not None:
            self._defaultPlayOptions = defaultPlaybackOptions

        if websocketOptions is not None:
            self._websocketOptions = websocketOptions

        self._renew_socket()
    def _renew_socket(self):
        self._websocket_ready_event.clear()
        self._websocket = None
        self._currentGenOptions = self._voice._complete_generation_options(self._generationOptions) # noqa - Yes, it's internal.
        self._websocket = self._voice._generate_websocket(self._websocketOptions, self._generationOptions) # noqa - Yes, it's internal.
        self._websocket_ready_event.set()
        self._last_renewal_time = time.perf_counter()

    def _ping_function(self):
        while not self._interruptEvent.is_set():
            self._websocket_ready_event.wait()
            pong = self._websocket.ping()
            ping_replied = pong.wait(timeout=1)
            if (not ping_replied and not self._interruptEvent.is_set()) or time.perf_counter()-self._last_renewal_time > 17:
                #websocket is dead or stale. Nuke it and set up a new one.
                self._websocket.close_socket()
                #Stale time is 17 seconds since websocket timeout is 20.
                #This is required to avoid situations where a new audio might come in,
                #and the websocket is used despite it actually being dead, because the ping timeout hasn't expired yet.
                self._renew_socket()
            time.sleep(3)   #Let's avoid hammering the websocket with pings...
        self._websocket.close_socket()
    def queue_audio(self, prompt:Union[Iterator[str], AsyncIterator], playbackOptions:PlaybackOptions=None) -> tuple[Future[sd.OutputStream], Future[queue.Queue]]:
        """
        Queues up an audio to be generated and played back.

        Arguments:
            prompt: The iterator to use for the generation.
            playbackOptions: Overrides the playbackOptions for this generation.

        Returns:
            tuple: A tuple consisting of two futures, the one for the playback stream and the one for the transcript queue.
        """
        if self._interruptEvent.is_set():
            raise ValueError("Do not re-use a closed ReusableInputStreamer!")
        if playbackOptions is None:
            playbackOptions = self._defaultPlayOptions
        if inspect.isasyncgen(prompt):
            prompt = SyncIterator(prompt)

        playbackOptions = dataclasses.replace(playbackOptions)  #Ensure it's a copy.
        transcript_queue_future = concurrent.futures.Future()
        playback_stream_future = concurrent.futures.Future()

        if not playbackOptions.runInBackground:
            #Add an event and wait until it's done with the playback.
            playback_done_event = threading.Event()
            old_playbackend = playbackOptions.onPlaybackEnd
            def wrapper():
                playback_done_event.set()
                old_playbackend()
            playbackOptions.onPlaybackEnd = wrapper
            self._iterator_queue.put((prompt, playbackOptions, playback_stream_future, transcript_queue_future ))
            playback_done_event.wait()
        else:
            self._iterator_queue.put((prompt, playbackOptions, playback_stream_future, transcript_queue_future))
        return playback_stream_future, transcript_queue_future

    def _consumer_thread(self):
        prompt, playbackOptions, stream_future, transcript_future = None, None, None, None
        while not self._interruptEvent.is_set():
            try:
                prompt, playbackOptions, stream_future, transcript_future = self._iterator_queue.get(timeout=5)
            except queue.Empty:
                continue
            finally:
                if self._interruptEvent.is_set():
                    return

            while not self._websocket_ready_event.is_set():
                self._websocket_ready_event.wait(timeout=1)

                if self._interruptEvent.is_set():
                    return

            current_socket = self._websocket
            threading.Thread(target=self._renew_socket).start() # Forcefully renew socket now that it was already acquired.

            from elevenlabslib.Voice import _NumpyMp3Streamer, _NumpyRAWStreamer, _NumpyPlaybacker
            streamer: Union[_NumpyMp3Streamer, _NumpyRAWStreamer]
            temp_future = concurrent.futures.Future()
            temp_future.set_result(current_socket)
            if "mp3" in self._currentGenOptions.output_format:
                streamer = _NumpyMp3Streamer(temp_future, self._currentGenOptions, self._websocketOptions, prompt, None)
            else:
                streamer = _NumpyRAWStreamer(temp_future, self._currentGenOptions, self._websocketOptions, prompt, None)

            transcript_future.set_result(streamer.transcript_queue)

            player = _NumpyPlaybacker(streamer.playback_queue, playbackOptions, self._currentGenOptions)
            streaming_thread = threading.Thread(target=streamer.begin_streaming)
            playback_thread = threading.Thread(target=player.begin_playback, args=(stream_future,))
            streaming_thread.start()
            playback_thread.start()

            self._currentStream = stream_future.result(timeout=60)

            streaming_thread.join()
            playback_thread.join()
            current_socket.close_socket()

class ReusableInputStreamerNoPlayback:
    """
    This is basically a reusable wrapper around a websocket connection.
    """
    def __init__(self, voice:Voice,
                 generationOptions:GenerationOptions=GenerationOptions(latencyOptimizationLevel=3),
                 websocketOptions:WebsocketOptions=WebsocketOptions()
                 ):
        self._voice = voice
        self._websocket_ready_event = threading.Event()
        self._generationOptions = generationOptions
        self._interruptEvent = threading.Event()
        self._websocket: websockets.sync.client.ClientConnection = None
        self._websocketOptions = websocketOptions
        self._currentGenOptions: GenerationOptions = None   #These are the options tied to the current voice.
        self._last_renewal_time = 0
        self._ping_thread = threading.Thread(target=self._ping_function)
        self._iterator_queue = queue.Queue()

        self._renew_socket()
        self._ping_thread.start()
        threading.Thread(target=self._consumer_thread).start()  # Starts the consumer thread

    def change_voice(self, voice:Voice):
        self._voice = voice
        self._renew_socket()
    def stop(self):
        """
        Stops the websocket.
        """
        self._interruptEvent.set()
        if self._websocket is not None:
            self._websocket.close_socket()

    def abort(self):
        """
        Stops the websocket.
        """
        self.stop()
        if self._websocket is not None:
            self._websocket.close_socket()
    def change_settings(self, generationOptions:GenerationOptions=None, defaultPlaybackOptions:PlaybackOptions=None, websocketOptions:WebsocketOptions=None):
        """
        Allows you to change the settings and then re-establishes the socket.
        """
        if generationOptions is not None:
            self._generationOptions = generationOptions

        if websocketOptions is not None:
            self._websocketOptions = websocketOptions

        self._renew_socket()
    def _renew_socket(self):
        self._websocket_ready_event.clear()
        self._websocket = None
        self._currentGenOptions = self._voice._complete_generation_options(self._generationOptions) # noqa - Yes, it's internal.
        self._websocket = self._voice._generate_websocket(self._websocketOptions, self._generationOptions) # noqa - Yes, it's internal.
        self._websocket_ready_event.set()
        self._last_renewal_time = time.perf_counter()

    def _ping_function(self):
        while not self._interruptEvent.is_set():
            self._websocket_ready_event.wait()
            pong = self._websocket.ping()
            ping_replied = pong.wait(timeout=1)
            if (not ping_replied and not self._interruptEvent.is_set()) or time.perf_counter()-self._last_renewal_time > 17:
                #websocket is dead or stale. Nuke it and set up a new one.
                self._websocket.close_socket()
                #Stale time is 17 seconds since websocket timeout is 20.
                #This is required to avoid situations where a new audio might come in,
                #and the websocket is used despite it actually being dead, because the ping timeout hasn't expired yet.
                self._renew_socket()
            time.sleep(3)   #Let's avoid hammering the websocket with pings...
        self._websocket.close_socket()
    def queue_audio(self, prompt:Union[Iterator[str], AsyncIterator]) -> tuple[Future[queue.Queue], Future[queue.Queue]]:
        """
        Queues up an audio to be generated and played back.

        Arguments:
            prompt: The iterator to use for the generation.
        Returns:
            tuple: A tuple consisting of two futures, one for the numpy audio queue and one for the transcript queue.
        """
        if self._interruptEvent.is_set():
            raise ValueError("Do not re-use a closed ReusableInputStreamer!")

        if inspect.isasyncgen(prompt):
            prompt = SyncIterator(prompt)

        transcript_queue_future = concurrent.futures.Future()
        audio_queue_future = concurrent.futures.Future()

        self._iterator_queue.put((prompt, audio_queue_future, transcript_queue_future))
        return audio_queue_future, transcript_queue_future

    def _consumer_thread(self):
        prompt, audio_queue_future, transcript_queue_future = None, None, None
        while not self._interruptEvent.is_set():
            try:
                prompt, audio_queue_future, transcript_queue_future = self._iterator_queue.get(timeout=5)
            except queue.Empty:
                continue
            finally:
                if self._interruptEvent.is_set():
                    return

            while not self._websocket_ready_event.is_set():
                self._websocket_ready_event.wait(timeout=1)

                if self._interruptEvent.is_set():
                    return

            current_socket = self._websocket
            threading.Thread(target=self._renew_socket).start() # Forcefully renew socket now that it was already acquired.
            from elevenlabslib.Voice import _NumpyMp3Streamer, _NumpyRAWStreamer
            streamer: Union[_NumpyMp3Streamer, _NumpyRAWStreamer]
            temp_future = concurrent.futures.Future()
            temp_future.set_result(current_socket)
            if "mp3" in self._currentGenOptions.output_format:
                streamer = _NumpyMp3Streamer(temp_future, self._currentGenOptions, self._websocketOptions, prompt, None)
            else:
                streamer = _NumpyRAWStreamer(temp_future, self._currentGenOptions, self._websocketOptions, prompt, None)

            audio_queue_future.set_result(streamer.playback_queue)
            transcript_queue_future.set_result(streamer.transcript_queue)
            streamer.begin_streaming()
            current_socket.close_socket()


def run_ai_speech_classifier(audioBytes:bytes):
    """
    Runs Elevenlabs' AI speech classifier on the provided audio data.
    Parameters:
        audioBytes: The bytes of the audio file (mp3, wav, most formats should work) you want to analzye

    Returns:
        Dict containing all the information returned by the tool (usually just the probability of it being AI generated)
    """
    data = io.BytesIO(audioBytes)
    files = {'file': ('audioSample.mp3', data, 'audio/mpeg')}
    response = _api_multipart("/moderation/ai-speech-classification", headers=None, data=None, filesData=files)
    return response.json()

class _PlayableItem:    #Just a wrapper class to avoid code re-use
    def __init__(self):
        self._audioData = None
    def _fetch_and_cache_audio(self, fetch_method):
        if self._audioData is None:
            response = fetch_method()
            self._audioData = response.content
        return self._audioData
    def get_audio_bytes(self) -> bytes:
        #Designed to just be overridden.
        """
        Retrieves the audio bytes associated with this object.
        Note:
            The audio will be cached so that it's not downloaded every time this is called.
        Returns:
            bytes: a bytes object containing the audio in whatever format it was originally uploaded in.
        """
        pass
    def play_audio_v2(self, playbackOptions:PlaybackOptions = PlaybackOptions()):
        """
        Plays the audio associated with this object.

        Args:
            playbackOptions (PlaybackOptions): Options for the audio playback such as the device to use and whether to run in the background.
        Returns:
            The sounddevice OutputStream of the playback.
        """
        audioBytes = self.get_audio_bytes()
        return play_audio_v2(audioBytes, playbackOptions)

def play_audio_v2(audioData:Union[bytes, numpy.ndarray], playbackOptions:PlaybackOptions=PlaybackOptions(), audioFormat:Union[str, GenerationOptions]="mp3_44100_128") -> sd.OutputStream:
    """
    Plays the given audio and calls the given functions.

    Parameters:
         audioData (bytes|numpy.ndarray): The audio data to play, either in bytes or as a numpy array (float32!)
         playbackOptions (PlaybackOptions, optional): The playback options.
         audioFormat (str, optional): The format of audioData - same formats used for GenerationOptions. If not mp3 (or numpy array), then has to specify the samplerate in the format (like pcm_44100). Defaults to mp3.
    Returns:
        None
    """
    # Let's make sure the user didn't just forward a tuple from one of the other functions...
    if isinstance(audioData, tuple):
        for item in audioData:
            if isinstance(item, bytes):
                audioData = item

    if isinstance(audioFormat, GenerationOptions):
        audioFormat = audioFormat.output_format

    if "highest" in audioFormat:
        if "mp3" in audioFormat:
            audioFormat = "mp3_44100_128"
        else:
            raise ValueError("Please specify the actual samplerate in the format. Use user.get_real_audio_format if necessary.")
    playbackWrapper = _SDPlaybackWrapper(audioData, playbackOptions, audioFormat)

    if not playbackOptions.runInBackground:
        with playbackWrapper.stream:
            playbackWrapper.endPlaybackEvent.wait()
    else:
        playbackWrapper.stream.start()
        return playbackWrapper.stream

def _audio_is_raw(audioData:bytes):
    #Checks whether the provided audio file is PCM or some other format.
    try:
        soundfile.SoundFile(io.BytesIO(audioData))
        return False
    except soundfile.LibsndfileError:
        return True

def raw_to_wav(rawData:bytes, samplerate:int, subtype:str) -> bytes:
    # Let's make sure the user didn't just forward a tuple from one of the other functions...
    if isinstance(rawData, tuple):
        for item in rawData:
            if isinstance(item, bytes):
                rawData = item

    soundFile = sf.SoundFile(io.BytesIO(rawData), format="RAW", subtype=subtype, channels=1, samplerate=samplerate)
    wavIO = io.BytesIO()
    sf.write(wavIO, soundFile.read(), soundFile.samplerate, format="wav")

    return wavIO.getvalue()
def ulaw_to_wav(ulawData:bytes, samplerate:int) -> bytes:
    """
    This function converts ULAW audio to a WAV.

    Parameters:
        ulawData (bytes): The ULAW audio data.
        samplerate (int): The sample rate of the audio

    Returns:
        The bytes of the wav file.
    """
    return raw_to_wav(ulawData, samplerate, "ULAW")
def pcm_to_wav(pcmData:bytes, samplerate:int) -> bytes:
    """
    This function converts PCM audio to a WAV.

    Parameters:
        pcmData (bytes): The PCM audio data.
        samplerate (int): The sample rate of the audio

    Returns:
        The bytes of the wav file.
    """

    return raw_to_wav(pcmData, samplerate, "PCM_16")

def _open_soundfile(audioData:bytes, audioFormat:str) -> soundfile.SoundFile:
    audioFormat = audioFormat.lower()
    samplerate = int(audioFormat.split("_")[1])
    if "ulaw" in audioFormat:
        return soundfile.SoundFile(io.BytesIO(audioData), format="RAW", subtype="ULAW", channels=1, samplerate=samplerate)
    if "pcm" in audioFormat:
        return soundfile.SoundFile(io.BytesIO(audioData), format="RAW", subtype="PCM_16", channels=1, samplerate=samplerate)
    else:
        return soundfile.SoundFile(io.BytesIO(audioData))

def save_audio_v2(audioData:Union[bytes, numpy.ndarray], saveLocation:Union[BinaryIO,str], outputFormat:str, inputFormat:Union[str, GenerationOptions]="mp3_44100_128") -> None:
    """
    This function saves the audio data to the specified location OR file-like object.
    soundfile is used for the conversion, so it supports any format it does.

    Parameters:
        audioData (bytes): The audio data.
        saveLocation (str|BinaryIO): The path (or file-like object) where the data will be saved.
        outputFormat (str): The format in which the audio will be saved (mp3/wav/ogg/etc).
        inputFormat: The format of audioData - same formats used for GenerationOptions. If not mp3, then has to specify the samplerate in the format (like pcm_44100). Defaults to mp3.
    """

    if isinstance(inputFormat, GenerationOptions):
        inputFormat = inputFormat.output_format

    if "highest" in inputFormat:
        if "mp3" in inputFormat:
            inputFormat = "mp3_44100_128"
        else:
            raise ValueError("Please specify the actual samplerate in the format. Use user.get_real_audio_format if necessary.")

    samplerate = int(inputFormat.split("_")[1])
    if isinstance(audioData, bytes):
        # Let's make sure the user didn't just forward a tuple from one of the other functions...
        if isinstance(audioData, tuple):
            for item in audioData:
                if isinstance(item, bytes):
                    audioData = item


        tempSoundFile = soundfile.SoundFile(io.BytesIO(audioData))
        numpy_data = tempSoundFile.read()
    else:
        numpy_data = audioData

    if isinstance(saveLocation, str):
        with open(saveLocation, "wb") as fp:
            sf.write(fp, numpy_data, samplerate, format=outputFormat)
    else:
        sf.write(saveLocation, numpy_data, samplerate, format=outputFormat)
        if callable(getattr(saveLocation,"flush")):
            saveLocation.flush()


#This class is used to make async generators into normal iterators for input streaming. I didn't feel like reworking all the code to be async instead of multithreaded.
class SyncIterator:
    def __init__(self, async_iter):
        self.shared_queue = queue.Queue()
        self.async_iter = async_iter
        self.async_thread = threading.Thread(target=self.async_thread_target)
        self.async_thread.start()
    def __iter__(self):
        return self

    def async_thread_target(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def gather_data():
            async for item in self.async_iter:
                self.shared_queue.put(item)
            self.shared_queue.put(None)  # Sentinel value for completion

        loop.run_until_complete(gather_data())

    def __next__(self):
        item = self.shared_queue.get()
        if item is None:  # Sentinel value indicating end of data
            raise StopIteration
        return item


#This class just helps with the callback stuff.
class _SDPlaybackWrapper:
    def __init__(self, audioData:Union[bytes, numpy.ndarray], playbackOptions:PlaybackOptions, audioFormat:str):
        channels = 1
        samplerate = int(audioFormat.split("_")[1])
        if isinstance(audioData, bytes):
            soundFile = _open_soundfile(audioData, audioFormat)
            soundFile.seek(0)
            self.data:np.ndarray = soundFile.read(always_2d=True)
            channels = soundFile.channels
            samplerate = soundFile.samplerate   #Just in case soundfile disagrees on the samplerate.
        else:
            shape = audioData.shape
            if len(shape) == 1:
                channels = 1
            elif len(shape) == 2:
                channels = shape[1]
            self.data:np.ndarray = audioData.reshape(-1, channels)

        self.data = playbackOptions.audioPostProcessor(self.data, samplerate)

        self.onPlaybackStart = playbackOptions.onPlaybackStart
        self.onPlaybackEnd = playbackOptions.onPlaybackEnd
        self.startPlaybackEvent = threading.Event()
        self.endPlaybackEvent = threading.Event()
        self.currentFrame = 0

        self.stream = sd.OutputStream(channels=channels,
            callback=self.callback,
            samplerate=samplerate,
            device=playbackOptions.portaudioDeviceID or sd.default.device,
            finished_callback=self.end_playback)

    def callback(self, outdata, frames, time, status):
        if status:
            logging.warning(status)

        if not self.startPlaybackEvent.is_set():    #Ensure this is only fired once
            self.startPlaybackEvent.set()
            self.onPlaybackStart()

        chunksize = min(len(self.data) - self.currentFrame, frames)
        outdata[:chunksize] = self.data[self.currentFrame:self.currentFrame + chunksize]
        if chunksize < frames:
            outdata[chunksize:] = 0
            raise sd.CallbackStop()
        self.currentFrame += chunksize
    def end_playback(self):
        self.onPlaybackEnd()
        self.endPlaybackEvent.set()

class _PeekQueue(queue.Queue):
    def peek(self):
        with self.mutex:
            return list(self.queue)[0]

    def snapshot(self):
        with self.mutex:
            return list(self.queue)

def _api_tts_with_concurrency(requestFunction:callable, generationID:str, generationQueue:_PeekQueue) -> requests.Response:
    #Just a helper function which does all the concurrency stuff for TTS calls.
    waitMultiplier = 1
    response = None
    try:
        response = requestFunction()
        response.raise_for_status() #Just in case the callable isn't a function that already does this.
    except requests.exceptions.RequestException as e:
        response_json = e.response.json()
        response_handled = False

        if "detail" in response_json:
            error_detail = response_json["detail"]
            if "status" in error_detail:
                if error_detail["status"] == "too_many_concurrent_requests" or error_detail["status"] == "system_busy":
                    if error_detail["status"] == "too_many_concurrent_requests":
                        logging.warning(f"{generationID} - broke concurrency limits, handling the cooldown...")
                    else:
                        logging.warning(f"{generationID} - system overloaded, handling the cooldown...")
                    # Insert this in the user's "waiting to be generated" queue.
                    generationQueue.put(generationID)
                    response = None
                    response_handled = True
                elif error_detail["status"] == "model_can_not_do_voice_conversion":
                    raise RuntimeError(error_detail["message"])
        if not response_handled:
            logging.error(response_json)
            raise e
    if response is None:
        while True:
            try:
                peeked = generationQueue.peek()
                if peeked == generationID:
                    response = requestFunction()
                    response.raise_for_status()
                    generationQueue.get()
                    break
                else:
                    logging.debug(f"\nCurrent first is {peeked}, we are {generationID}\n")
                    logging.debug(f"\nOther items are first in queue, waiting for 0.5s\n")
                    time.sleep(0.5)  # The time to peek at the queue is constant.
            except requests.exceptions.RequestException as e:
                response_json = e.response.json()
                error_status = response_json["detail"]["status"]
                if error_status == "too_many_concurrent_requests" or error_status == "system_busy":
                    logging.warning(f"\nSystem overloaded, waiting for {0.5 * waitMultiplier}s\n")
                    time.sleep(0.5 * waitMultiplier)  # Just wait a moment and try again.
                    waitMultiplier += 1
                    continue
                raise e

    return response

#Modified from the official python library - https://github.com/elevenlabs/elevenlabs-python
def _text_chunker(chunks: Iterator[Union[str, dict]], generation_options:GenerationOptions, websocket_options:WebsocketOptions) -> Iterator[dict]:
    """Used during input streaming to chunk text blocks and set last char to space"""
    splitters = (".", ",", "?", "!", ";", ":", "—", "-", "(", ")", "[", "]", "}", " ")
    buffer = ""

    for text_or_dict in chunks:
        if isinstance(text_or_dict, dict):
            yielded_dict = text_or_dict
            chunk_text = text_or_dict.get("text","")
        else:
            yielded_dict = {"text": text_or_dict,
                            "try_trigger_generation": websocket_options.try_trigger_generation,
                            "flush": False}
            chunk_text = text_or_dict

        if buffer.endswith(splitters):
            if buffer.endswith(" "):
                yielded_dict["text"] = apply_pronunciations(buffer, generation_options)
            else:
                yielded_dict["text"] = apply_pronunciations(buffer + " ", generation_options)
            yield yielded_dict
            buffer = chunk_text
        elif chunk_text.startswith(splitters):
            output = buffer + chunk_text[0]
            if output.endswith(" "):
                yielded_dict["text"] = apply_pronunciations(output, generation_options)
            else:
                yielded_dict["text"] = apply_pronunciations(output + " ", generation_options)
            yield yielded_dict
            buffer = chunk_text[1:]
        else:
            buffer += chunk_text
    if buffer != "":
        yield {"text": apply_pronunciations(buffer + " ", generation_options), "try_trigger_generation": False, "flush": False} #We're at the end, so it's not like it actually matters.

def _reformat_transcript(alignment_data, current_audio_ms=0) -> (list, int):
    # This is the block that handles re-formatting transcripts.
    formatted_list = list()
    is_websocket_transcript = False
    if "chars" in alignment_data:
        is_websocket_transcript = True
        char_array = alignment_data["chars"]
    else:
        char_array = alignment_data["characters"]

    for i in range(len(char_array)):
        if is_websocket_transcript:
            new_char = {
                "character": alignment_data["chars"][i],
                "start_time_ms": alignment_data["charStartTimesMs"][i] + current_audio_ms,
                "duration_ms": alignment_data["charDurationsMs"][i]
            }
        else:
            new_char = {
                "character": alignment_data["characters"][i],
                "start_time_ms": alignment_data["character_start_times_seconds"][i]*1000 + current_audio_ms,
                "duration_ms": alignment_data["character_end_times_seconds"][i]*1000
            }
        formatted_list.append(new_char)

        # TODO: Remove cutout functionality - we have pre and post text now.
        #if self._enable_cutout:
        #    if new_char["character"] == '"':
        #        if self._start_frame is None:
        #            self._start_frame = math.ceil((new_char["start_time_ms"] + new_char["duration_ms"] * (1 - self._prompting_options.open_quote_duration_multiplier)) * self.sample_rate / 1000)
        #        else:
        #            self._end_frame = math.floor((new_char["start_time_ms"] + new_char["duration_ms"] * self._prompting_options.close_quote_duration_multiplier) * self.sample_rate / 1000)

    new_audio_ms = formatted_list[-1]["start_time_ms"] + formatted_list[-1]["duration_ms"]
    return formatted_list, new_audio_ms

def io_hash_from_audio(source_audio:Union[bytes, BinaryIO]) -> (BinaryIO, str):
    audio_hash = ""
    audio_io = None
    if isinstance(source_audio, bytes):
        audio_hash = zlib.crc32(source_audio)
        audio_io = io.BytesIO(source_audio)
    elif isinstance(source_audio, io.IOBase):
        source_audio.seek(0)
        audio_hash = zlib.crc32(source_audio.read())
        source_audio.seek(0)
        audio_io = source_audio

    return audio_io, audio_hash




#Audio cutting/ONNX stuff.
def sts_long_audio(source_audio:Union[bytes, BinaryIO], voice:Voice, generation_options:GenerationOptions = GenerationOptions(model="eleven_multilingual_sts_v2"), speech_threshold:float=0.5) -> bytes:
    """
    Allows you to process a long audio file with speech to speech automatically, using Silero-VAD to split it up naturally.

    Arguments:
        source_audio (bytes|BinaryIO): The source audio.
        voice (Voice): The voice to use for STS.
        generation_options (GenerationOptions): The generation options to use. The model specified must support STS.
        speech_threshold (float): The likelyhood that a segment must be speech for it to be recognized (0.5/50% works for most audio files).
    Returns:
        bytes: The bytes of the final audio, all concatenated, in mp3 format.
    """
    if isinstance(source_audio, io.IOBase):
        source_audio.seek(0)
        source_audio = source_audio.read()

    #Only mp3 works. So we default to mp3 highest.
    if "mp3" not in generation_options.output_format:
        generation_options = dataclasses.replace(generation_options, output_format="mp3_highest")
        generation_options = voice.linkedUser.get_real_audio_format(generation_options)

    audio_segments = split_audio(source_audio, speech_threshold=speech_threshold)

    destination_io = io.BytesIO()
    tts_segments:List[bytes] = []
    tts_futures:List[concurrent.futures.Future] = []

    #Queue them all up for generation
    for idx, audio_io in enumerate(audio_segments):
        audio_io.seek(0)
        tts_future, _ = voice.generate_audio_v3(audio_io, generation_options=generation_options)
        tts_futures.append(tts_future)

    #Get the results
    for idx, tts_future in enumerate(tts_futures):
        tts_segment = tts_future.result()
        data, samplerate = sf.read(io.BytesIO(tts_segment), dtype="float32")
        tts_segments.append(data)

    concatenated_samples = np.concatenate(tts_segments)

    #Technically, the section below is useless. I'm keeping it just in case they add support for other formats for STS.
    audio_extension = ""
    if "mp3" in generation_options.output_format: audio_extension = "mp3"
    if "pcm" in generation_options.output_format: audio_extension = "wav"
    if "ulaw" in generation_options.output_format: audio_extension = "wav"

    save_audio_v2(concatenated_samples, destination_io, audio_extension, generation_options)
    destination_io.seek(0)

    return destination_io.read()
