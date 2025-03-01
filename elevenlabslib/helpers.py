from __future__ import annotations

import asyncio
import audioop
import base64
import concurrent.futures
import warnings
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

import websockets
import websockets.sync.client
from tokenizers import Tokenizer

# These are hardcoded because they just plain work. If you really want to change them, please be careful.
_playbackBlockSize = 2048
_downloadChunkSize = 4096

if TYPE_CHECKING:
    from elevenlabslib.HistoryItem import HistoryItem
    from elevenlabslib.PronunciationDictionary import PronunciationDictionary
    from elevenlabslib.Model import Model

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

_roberta_model = None
_roberta_model_lock = threading.Lock()
class CategoryShorthands(Enum):
    generated = "gen"
    professional = "pvc"
    cloned = "ivc"
    premade = "pre"

class ModelShorthands(Enum):
    eleven_multilingual_v2 = "m2"
    eleven_english_v2 = "e2"
    eleven_multilingual_v1 = "e1"
    eleven_turbo_v2 = "t2"
    eleven_turbo_v2_5 = ""

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
        pronunciation_dictionaries (List[PronunciationDictionary], optional): The pronunciation dictionaries to apply to this request (max 3).
        seed (int, optional): The seed. to use for this generation (Determinism is not guaranteed)
        speed (float, optional): The speed setting. Between 0.7 and 1.2. Defaults to 1.
        language_code (str, optional): An ISO 639-1 code, used to enforce a language for the model. Currently turbo v2.5 only.

    Warning:
        The style and use_speaker_boost parameters are only available on v2 models, and will be ignored for v1 models.

        Setting style to higher than 0 and enabling use_speaker_boost will both increase latency.

        output_format is currently ignored when using speech to speech.

    Warning:
        Using pcm_highest and mp3_highest will cache the resulting quality for the user object. You can use user.update_audio_quality() to force an update.
    """
    model_id: Optional[str] = dataclasses.field(default=None, init=True, repr=False)
    latencyOptimizationLevel: int = 0
    speed: Optional[float] = 1
    stability: Optional[float] = None
    similarity_boost: Optional[float] = None
    style: Optional[float] = None
    use_speaker_boost: Optional[bool] = None
    model: Optional[Union[Model, str]] = "eleven_multilingual_v2"
    output_format:str = "mp3_highest"
    seed:Optional[int] = None
    language_code: Optional[str] = None
    pronunciation_dictionaries: Optional[List[PronunciationDictionary]] = None

    def __post_init__(self):
        if self.model_id:
            self.model = self.model_id
        if not self.model_id:
            if isinstance(self.model, str):
                self.model_id = self.model
            else:
                self.model_id = self.model.modelID

        #Validate values
        for var in [self.stability, self.similarity_boost, self.style]:
            if var is not None and (var < 0 or var > 1):
                raise ValueError("Please provide a value between 0 and 1 for stability, similarity_boost, and style.")

        if (self.latencyOptimizationLevel < 0 or self.latencyOptimizationLevel > 4) and self.latencyOptimizationLevel != -99:
            raise ValueError("Please provide a value between 0 and 4 for latencyOptimizationLevel")
        if self.speed < 0.7 or self.speed > 1.2:
            raise ValueError("Please provide a value between 0.7 and 1.2 for speed.")
        validOutputFormats = ["mp3_44100_64", "mp3_44100_96", "mp3_44100_128","mp3_44100_192", "pcm_16000", "pcm_22050", "pcm_24000", "pcm_44100", "mp3_highest","pcm_highest", "ulaw_8000"]

        if self.output_format not in validOutputFormats:
            raise ValueError("Selected output format is not valid.")

    def get_voice_settings_dict(self) -> dict:
        return {
            "similarity_boost":self.similarity_boost,
            "stability":self.stability,
            "style":self.style,
            "use_speaker_boost":self.use_speaker_boost,
            "speed": self.speed
        }

@dataclasses.dataclass
class WebsocketOptions:
    """
    This class holds the options for the websocket endpoint.

    Parameters:
        chunk_length_schedule (list[int], optional): Chunking schedule for generation. If you pass [50, 120, 500], the first audio chunk will be generated after recieving 50 characters, the second after 120 more (so 170 total), and the third onwards after 500. Defaults to [50], so always generating ASAP.
        try_trigger_generation (bool, optional): Whether to try and generate a chunk of audio at >50 characters, regardless of the chunk_length_schedule. Defaults to False, sent with every message (but can be overridden).
        enable_ssml_parsing (bool, optional): Whether to enable parsing of SSML tags, such as breaks or pronunciations. Increases latency. Defaults to False.
        inactivity_timeout (float, optional): The time in seconds to wait before closing the connection if no messages are sent. Defaults to 20.
        sync_alignment (bool, optional): Whether to include timing data with every audio chunk. Defaults to False.
        auto_mode (bool, optional): Reduces latency by disabling all buffers. It is ONLY recommended when sending full sentences or phrases. Defaults to False.
    """
    try_trigger_generation: bool = False
    chunk_length_schedule: List[int] = dataclasses.field(default_factory=lambda: [125])
    enable_ssml_parsing: bool = False
    inactivity_timeout: Optional[float] = 20
    sync_alignment: bool = False
    auto_mode: bool = False
    def __post_init__(self):
        for value in self.chunk_length_schedule:
            if not(50 <= value <= 500):
                raise ValueError("Chunk length outside the [50,500] range.")

emotion_prompts = {
        'admiration': "she said admiringly.",
        'amusement': "she said with amusement.",
        'anger': "she said angrily.",
        'annoyance': "she said with annoyance.",
        'approval': "she said approvingly.",
        'caring': "she said caringly.",
        'confusion': "she said with confusion.",
        'curiosity': "she said curiously.",
        'desire': "she said with desire.",
        'disappointment': "she said with disappointment.",
        'disapproval': "she said disapprovingly.",
        'disgust': "she said with disgust.",
        'embarrassment': "she said embarrassedly.",
        'excitement': "she said excitedly.",
        'fear': "she said fearfully.",
        'gratitude': "she said gratefully.",
        'grief': "she said with grief.",
        'joy': "she said joyfully.",
        'love': "she said lovingly.",
        'nervousness': "she said nervously.",
        'optimism': "she said optimistically.",
        'pride': "she said proudly.",
        'realization': "she said with realization.",
        'relief': "she said with relief.",
        'remorse': "she said remorsefully.",
        'sadness': "she said sadly.",
        'surprise': "she said with surprise.",
        'neutral': ""
    }

def get_emotion_for_prompt(prompt:str) -> str:
    global _roberta_model
    with _roberta_model_lock:
        if _roberta_model is None:
            model_url = "https://huggingface.co/SamLowe/roberta-base-go_emotions-onnx/resolve/main/onnx/model_quantized.onnx"
            from elevenlabslib._audio_cutter_helper import _download_onnx_model
            try:
                model_path = _download_onnx_model(model_url, "roberta.onnx")
                _roberta_model = _RobertaWrapper(model_path)
            except requests.exceptions.Timeout:
                _roberta_model = None
    if _roberta_model:
        return _roberta_model.get_emotions([prompt])[0]
    else:
        return "neutral"

@dataclasses.dataclass
class StitchingOptions:
    """
    This class holds the options for request stitching and prompting.

    Parameters:
        previous_text (str, optional): Prompt which will be place before the quoted text.
        next_text (str, optional): Prompt which will be placed after the quoted text.
        previous_request_ids (list[int|HistoryItem], optional): A list of request_ids or HistoryItems generated before this generation. Overrides previous_text.
        next_request_ids (list[int|HistoryItem], optional): A list of request_ids or HistoryItems generated after this generation. Overrides next_text.
        auto_next_text (bool, optional): Automatically appends a next_text appropriate for the prompt. Defaults to false, disabled if next_text is included.
    """
    previous_text:Optional[str] = None
    next_text:Optional[str] = None
    previous_request_ids: Optional[List[Union[int, HistoryItem]]] = None
    next_request_ids:Optional[List[Union[int, HistoryItem]]] = None
    auto_next_text:bool = False

    def __post_init__(self):
        self.previous_request_ids = [(x if isinstance(x, int) else x.requestID) for x in self.previous_request_ids] if self.previous_request_ids else None
        self.next_request_ids = [(x if isinstance(x, int) else x.requestID) for x in self.next_request_ids] if self.next_request_ids else None
        if self.next_text is not None:
            self.auto_next_text = False

def PromptingOptions(pre_prompt: str = "", post_prompt: str = "",
                     open_quote_duration_multiplier: Optional[float] = None,
                     close_quote_duration_multiplier: Optional[float] = None):
    warnings.warn(
        "PromptingOptions is deprecated. Use StitchingOptions instead.",
        DeprecationWarning,
        stacklevel=2
    )

    # Create and return a StitchingOptions instance
    return StitchingOptions(
        previous_text=pre_prompt,
        next_text=post_prompt
    )


@dataclasses.dataclass
class GenerationInfo:
    """
    This contains the information returned regarding a (non-websocket) generation.
    """
    history_item_id: Optional[str] = None
    request_id: Optional[str] = None
    tts_latency_ms: Optional[str] = None
    transcript: Optional[list[str]] = None
    character_cost: Optional[int] = None

@dataclasses.dataclass
class SFXOptions:
    """
    This contains the parameters for a sound effect generation.
    """
    duration_seconds: Optional[float] = None
    prompt_influence: Optional[float] = None
    def __post_init__(self):
        if self.duration_seconds and not (0.5 <= self.duration_seconds <= 22):
            raise ValueError("Please input a valid duration (between 0.5 and 22).")
        if self.prompt_influence and not (0 <= self.prompt_influence <= 1):
            raise ValueError("Please input a valid prompt influence (between 0 and 1).")


def run_ai_speech_classifier(audioBytes:bytes):
    """
    Runs Elevenlabs' AI speech classifier on the provided audio data.

    Parameters:
        audioBytes: The bytes of the audio file (mp3, wav, most formats should work) you want to analyze.

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

def _raw_to_wav(rawData:bytes, samplerate:int, subtype:str) -> bytes:
    # Let's make sure the user didn't just forward a tuple from one of the other functions...
    if isinstance(rawData, tuple):
        for item in rawData:
            if isinstance(item, bytes):
                rawData = item

    soundFile = sf.SoundFile(io.BytesIO(rawData), format="RAW", subtype=subtype, channels=1, samplerate=samplerate)
    wavIO = io.BytesIO()
    sf.write(wavIO, soundFile.read(), soundFile.samplerate, format="wav")

    return wavIO.getvalue()
def _ulaw_to_wav(ulawData:bytes, samplerate:int) -> bytes:
    """
    This function converts ULAW audio to a WAV.

    Parameters:
        ulawData (bytes): The ULAW audio data.
        samplerate (int): The sample rate of the audio

    Returns:
        The bytes of the wav file.
    """
    return _raw_to_wav(ulawData, samplerate, "ULAW")
def _pcm_to_wav(pcmData:bytes, samplerate:int) -> bytes:
    """
    This function converts PCM audio to a WAV.

    Parameters:
        pcmData (bytes): The PCM audio data.
        samplerate (int): The sample rate of the audio

    Returns:
        The bytes of the wav file.
    """

    return _raw_to_wav(pcmData, samplerate, "PCM_16")

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

def _edit_stream_settings(playbackBlockSize=None, downloadChunkSize=None) -> None:
    """
    This function lets you override the default values used for the streaming functions.

    Danger:
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
        if e.response is None:
            raise e
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
                yielded_dict["text"] = buffer
            else:
                yielded_dict["text"] = buffer + " "
            yield yielded_dict
            buffer = chunk_text
        elif chunk_text.startswith(splitters):
            output = buffer + chunk_text[0]
            if output.endswith(" "):
                yielded_dict["text"] = output
            else:
                yielded_dict["text"] = output + " "
            yield yielded_dict
            buffer = chunk_text[1:]
        else:
            buffer += chunk_text
    if buffer != "":
        yield {"text": buffer + " ", "try_trigger_generation": False, "flush": False} #We're at the end, so it's not like it actually matters.

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






class _AudioStreamer:
    def __init__(self, streamConnection: Future[Union[requests.Response, websockets.sync.client.ClientConnection]],
                 generation_options:GenerationOptions, websocket_options:WebsocketOptions, prompt: Union[str, Iterator[str], Iterator[dict], bytes, io.IOBase]):
        self._events: dict[str, threading.Event] = {
            "downloadDoneEvent": threading.Event()
        }

        self._current_audio_ms = 0
        self.transcript_queue = queue.Queue()   #Holds the transcripts for the audio data

        self.connection_future:Future[Union[requests.Response, websockets.sync.client.ClientConnection]] = streamConnection
        self.connection:Optional[Union[requests.Response, websockets.sync.client.ClientConnection]] = None

        self._generation_options = generation_options
        self.sample_rate = int(generation_options.output_format.split("_")[1])
        self.websocket_options = websocket_options
        self.channels = 1

        self._prompt = prompt

    def _stream_downloader_function(self):
        # This is the function running in the download thread.
        self.connection.raise_for_status()
        totalLength = 0
        logging.debug("Starting iter...")
        if isinstance(self._prompt, str):
            #Handle with transcripts
            for line in self.connection.iter_lines():
                if line:  # filter out keep-alive new line
                    response_dict = json.loads(line.decode("utf-8"))
                    if response_dict["alignment"] is not None:
                        formatted_list, self._current_audio_ms = _reformat_transcript(response_dict["alignment"], self._current_audio_ms)
                        if self.transcript_queue is not None:
                            self.transcript_queue.put(formatted_list)

                    chunk = base64.b64decode(response_dict["audio_base64"])
                    self._stream_downloader_chunk_handler(chunk)
                    totalLength += len(chunk)
            self.transcript_queue.put(None)  # We're done with the transcripts
        else:
            #No transcript - old method
            for chunk in self.connection.iter_content(chunk_size=_downloadChunkSize):
                self._stream_downloader_chunk_handler(chunk)
                totalLength += len(chunk)

        logging.debug("Download finished - " + str(totalLength) + ".")
        self._events["downloadDoneEvent"].set()
        return

    def _stream_downloader_function_websockets(self):
        totalLength = 0
        logging.debug("Starting iter...")
        self.connection:websockets.sync.client.ClientConnection
        def sender():
            for data_dict in _text_chunker(self._prompt, self._generation_options, self.websocket_options):
                try:
                    self.connection.send(json.dumps(data_dict))
                except websockets.exceptions.ConnectionClosedError as e:
                    logging.exception(f"Generation failed, shutting down: {e}")
                    raise e

            self.connection.send(json.dumps(dict(text=""))) # Send end of stream

        sender_thread = threading.Thread(target=sender)
        sender_thread.start()
        while True:
            try:
                data = json.loads(self.connection.recv()) #We block because we know we're waiting on more messages.
                alignment_data = data.get("normalizedAlignment", None)
                if alignment_data is not None:
                    #This is the block that handles re-formatting transcripts.
                    formatted_list, self._current_audio_ms = _reformat_transcript(alignment_data, self._current_audio_ms)

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
        self.connection.close_socket() #Close it out.
    def _stream_downloader_chunk_handler(self, chunk):
        pass

class _NumpyMp3Streamer(_AudioStreamer):
    def __init__(self, streamConnection: Future[Union[requests.Response, websockets.sync.client.ClientConnection]],
                 generation_options:GenerationOptions, websocket_options:WebsocketOptions, prompt: Union[str, Iterator[str], Iterator[dict], bytes, io.IOBase]):
        super().__init__(streamConnection, generation_options, websocket_options, prompt)

        self._events.update({
            "headerReadyEvent": threading.Event(),
            "soundFileReadyEvent": threading.Event(),
            "blockDataAvailable": threading.Event()
        })

        self.playback_queue = queue.Queue()
        self.userfacing_queue = queue.Queue()

        self._audio_type = "mp3"
        self._frameSize = 4
        self._dtype = "float32"

        self.last_recreated_pos = 0  # Handling for a bug.
        self._buffer = b""
        self._audio_length = 0

        self._bytesFile = io.BytesIO()
        self._bytesSoundFile: Optional[sf.SoundFile] = None  # Needs to be created later.
        self._bytesLock = threading.Lock()

    def _stream_downloader_function(self):
        super()._stream_downloader_function()
        self._events["blockDataAvailable"].set()    #This call only happens once the download is entirely complete.

    def _stream_downloader_function_websockets(self):
        super()._stream_downloader_function_websockets()
        self._events["blockDataAvailable"].set()    #This call only happens once the download is entirely complete.


    #Func assumes it has lock
    def _sf_read_and_wait(self, dataToRead:int=-1) -> np.ndarray:
        preReadFramePos = self._bytesSoundFile.tell()
        readData = self._bytesSoundFile.read(dataToRead, dtype=self._dtype)

        # This is the handling for the bug.
        if len(readData) < dataToRead:
            logging.debug(f"Expected {dataToRead} bytes, but got back {len(readData)}")
            logging.debug("Insufficient data read. Check if we're at the end of the file.")
            curPos = self._bytesFile.tell()
            endPos = self._bytesFile.seek(0, os.SEEK_END)
            if curPos != endPos:
                logging.debug("We're not at the end of the file. Check if we're out of frames.")
                logging.debug("Recreating soundfile...")
                logging.debug(f"preReadFramePos: {preReadFramePos}")

                self._bytesFile.seek(0)
                newSF = sf.SoundFile(self._bytesFile, mode="r")

                logging.debug(f"postReadFramePos (before recreate): {self._bytesSoundFile.tell()}")
                newSF.seek(self._bytesSoundFile.tell() - int(len(readData)))

                self._bytesLock.release()
                if not self._events["downloadDoneEvent"].is_set():
                    logging.debug("Numpy bug happened before download is over. Waiting for blockDataAvailable.")
                    self._events["blockDataAvailable"].clear()
                    self._events["blockDataAvailable"].wait()
                else:
                    logging.debug("Numpy bug happened after download is over. Sleeping.")
                    time.sleep(0.1)
                self._bytesLock.acquire()

                newSF.seek(newSF.tell())
                frame_diff = newSF.frames - self._bytesSoundFile.frames
                if frame_diff > 0:
                    logging.debug(f"Frame counter was outdated by {frame_diff}.")
                    old_soundfile = self._bytesSoundFile
                    self._bytesSoundFile = newSF
                    del old_soundfile

                    readData = self._bytesSoundFile.read(dataToRead, dtype=self._dtype)
                    logging.debug("Now read " + str(len(readData)) +
                          " bytes. I sure hope that number isn't zero.")
                else:
                    logging.error(f"Frame counter was not outdated. What? This shouldn't happen.")
                    del newSF
            else:
                logging.debug("We are at the end. Nothing to do.")
        return readData.reshape(-1, self.channels)

    def _get_data_from_download_thread(self) -> np.ndarray:
        self._events["blockDataAvailable"].wait()  # Wait until a block of data is available.
        self._bytesLock.acquire()

        readData = self._sf_read_and_wait(_playbackBlockSize)

        #Now we seek back and forth to figure out how much "unread" data we have available.
        currentPos = self._bytesFile.tell()
        self._bytesFile.seek(0, os.SEEK_END)
        endPos = self._bytesFile.tell()
        self._bytesFile.seek(currentPos)
        remainingBytes = endPos - currentPos

        if remainingBytes < _playbackBlockSize and not self._events["downloadDoneEvent"].is_set():
            logging.debug("Marking no available blocks...")
            self._events["blockDataAvailable"].clear()  # Download isn't over and we've consumed enough data to where there isn't another block available.

        logging.debug("Read bytes: " + str(len(readData)) + "\n")

        self._bytesLock.release()
        return readData

    def begin_streaming(self):
        self._bytesFile = io.BytesIO()
        self._bytesSoundFile: Optional[sf.SoundFile] = None  # Needs to be created later.
        self.connection = self.connection_future.result()

        if isinstance(self.connection, requests.Response):
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

        while True:
            try:
                data = self._get_data_from_download_thread()
            except RuntimeError as e:
                logging.debug("File was looping at the end. Exiting.")
                break

            if len(data) == _playbackBlockSize:
                logging.debug("Putting " + str(len(data)) + " bytes in queue.")
                self.playback_queue.put(data)
                self.userfacing_queue.put(data)
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
                            self.playback_queue.put(data)
                            self.userfacing_queue.put(data)
                        break
                    else:
                        logging.debug("We're not at the end, yet we recieved less data than expected. This is a bug that was introduced with the update.")
        logging.debug("While loop done.")
        self.playback_queue.put(None)
        self.userfacing_queue.put(None)

        return

    def _stream_downloader_chunk_handler(self, chunk):
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


class _NumpyRAWStreamer(_AudioStreamer):
    def __init__(self, streamConnection: Future[Union[requests.Response, websockets.sync.client.ClientConnection]],
                 generation_options:GenerationOptions, websocket_options:WebsocketOptions, prompt: Union[str, Iterator[str], Iterator[dict], bytes, io.IOBase]):
        super().__init__(streamConnection, generation_options, websocket_options, prompt)
        parts = generation_options.output_format.lower().split("_")
        self._subtype = parts[0]

        self.playback_queue = queue.Queue()
        self.userfacing_queue = queue.Queue()

        self._audio_type = "raw"
        self._frameSize = 2
        self._dtype = "int16"

        self.last_recreated_pos = 0  # Handling for a bug.
        self._buffer = b""
        self._audio_length = 0

    def begin_streaming(self):
        logging.debug("Beginning stream...")
        self.connection = self.connection_future.result()

        if isinstance(self.connection, requests.Response):
            self._stream_downloader_function()
        else:
            self._stream_downloader_function_websockets()
        logging.debug("Stream done - putting None in the queue.")
        self.playback_queue.put(None)
        self.userfacing_queue.put(None)

        return

    def _stream_downloader_chunk_handler(self, chunk):
        if self._subtype.lower() == "ulaw":
            chunk = audioop.ulaw2lin(chunk, 2)
        self._buffer += chunk
        self._audio_length += len(chunk)

        while len(self._buffer) >= _playbackBlockSize*self._frameSize:
            curr_pos = (self._audio_length-len(self._buffer)) // self._frameSize
            frame_data, self._buffer = self._buffer[:_playbackBlockSize*self._frameSize], self._buffer[_playbackBlockSize*self._frameSize:]
            audioData = numpy.frombuffer(frame_data, dtype=self._dtype)
            audioData = audioData.reshape(-1, self.channels)
            audioData = audioData.astype(np.float32)
            audioData /= np.iinfo(np.int16).max

            self.playback_queue.put(audioData)
            self.userfacing_queue.put(audioData)

        if self._events["downloadDoneEvent"].is_set() and len(self._buffer) > 0:
            audioData = numpy.frombuffer(self._buffer, dtype=self._dtype)
            curr_pos = (self._audio_length - len(self._buffer)) // self._frameSize
            audioData = audioData.reshape(-1, self.channels)
            # Normalize to float32
            audioData = audioData.astype(np.float32)
            audioData /= np.iinfo(np.int16).max

            self.playback_queue.put(audioData)
            self.userfacing_queue.put(audioData)

            # Pad the end of the audio with silence to avoid the looping final chunk.s
            silence_chunk = np.zeros(_playbackBlockSize * self.channels, dtype=self._dtype).reshape(-1, self.channels)
            silence_chunk = silence_chunk.astype(np.float32)
            silence_chunk /= np.iinfo(np.int16).max
            for _ in range(2):
                self.playback_queue.put(silence_chunk)   #We don't add it to the duplicate queue, as this is just a fix for the playback.
            self.playback_queue.put(None)
            self.userfacing_queue.put(None)


class _NumpyPlaybacker:
    def __init__(self, audio_queue:queue.Queue, playbackOptions:PlaybackOptions, generationOptions:GenerationOptions):
        self._playback_start_fired = threading.Event()
        self._playback_finished = threading.Event()

        self._queue = audio_queue

        self._onPlaybackStart = playbackOptions.onPlaybackStart
        self._onPlaybackEnd = playbackOptions.onPlaybackEnd
        self._audioPostProcessor = playbackOptions.audioPostProcessor
        self._deviceID = playbackOptions.portaudioDeviceID or sd.default.device
        self._channels = 1
        self._sample_rate = int(generationOptions.output_format.split("_")[1])

    def begin_playback(self, future:concurrent.futures.Future):
        stream = sd.OutputStream(samplerate=self._sample_rate, blocksize=_playbackBlockSize,
                                 device=self._deviceID, channels=self._channels,
                                 dtype="float32", callback=self._callback, finished_callback=self._playback_finished.set)
        #dtype is guaranteed by the _NumpyStreamers to always be float32

        future.set_result(stream)
        logging.debug("Starting playback...")

        with stream:
            self._playback_finished.wait()  # Wait until playback is finished
            self._onPlaybackEnd()
            logging.debug(stream.active)
        logging.debug("Stream done.")
        return

    def _callback(self, outdata, frames, timeData, status):
        assert frames == _playbackBlockSize
        readData:np.ndarray = None
        while True:
            try:
                readData = self._queue.get(timeout=5)  # Download isn't over so we may have to wait.

                if readData is None:
                    logging.debug("Download (and playback) finished.")  # We're done.
                    raise sd.CallbackStop

                if len(readData) == 0:
                    logging.error("An empty item got into the queue. This shouldn't happen, but let's just skip it.")
                    continue
                break
            except queue.Empty as e:
                if self._playback_start_fired.is_set():
                    logging.error("Could not get an item within the timeout (after the playback began). This could lead to audio issues.")
                continue
                    # raise sd.CallbackAbort
        # We've read an item from the queue - process it.
        logging.debug("Applying postprocessing to audio...")
        readData = self._audioPostProcessor(readData, self._sample_rate)
        if not self._playback_start_fired.is_set():  # Ensure the callback only fires once.
            self._playback_start_fired.set()
            logging.debug("Firing onPlaybackStart...")
            self._onPlaybackStart()

        # Last read chunk was smaller than it should've been. It's either EOF or that stupid soundFile bug.
        if 0 < len(readData) < len(outdata):
            logging.debug("Data read smaller than it should've been.")
            logging.debug(f"Read {len(readData)} bytes but expected {len(outdata)}, padding...")

            outdata[:len(readData)] = readData
            outdata[len(readData):].fill(0)
        elif len(readData) == 0:
            logging.debug("Callback got empty data from the queue.")
        else:
            outdata[:] = readData


class _RobertaWrapper:
    def __init__(self, model_path):
        self.tokenizer = Tokenizer.from_pretrained("SamLowe/roberta-base-go_emotions")
        params = {**self.tokenizer.padding, "length": None}
        self.tokenizer.enable_padding(**params)

        import onnxruntime
        _options = onnxruntime.SessionOptions()
        _options.inter_op_num_threads, _options.intra_op_num_threads = os.cpu_count(), os.cpu_count()
        _providers = ["CPUExecutionProvider"]
        self.model = onnxruntime.InferenceSession(path_or_bytes=model_path, sess_options=_options, providers=_providers)

        self.output_names = [self.model.get_outputs()[0].name]

        self.labels = ['admiration', 'amusement', 'anger', 'annoyance', 'approval', 'caring', 'confusion', 'curiosity', 'desire', 'disappointment', 'disapproval', 'disgust', 'embarrassment',
                       'excitement', 'fear', 'gratitude', 'grief', 'joy', 'love', 'nervousness', 'optimism', 'pride', 'realization', 'relief', 'remorse', 'sadness', 'surprise', 'neutral']

    def _sigmoid(self, x):
        return 1.0 / (1.0 + np.exp(-x))

    def get_emotions(self, sentences):
        tokens_obj = self.tokenizer.encode_batch(sentences)

        input_feed_dict = {
            "input_ids": [t.ids for t in tokens_obj],
            "attention_mask": [t.attention_mask for t in tokens_obj]
        }

        logits = self.model.run(output_names=self.output_names, input_feed=input_feed_dict)[0]
        model_outputs = self._sigmoid(logits)

        emotion_labels = []
        for probas in model_outputs:
            top_result_index = np.argmax(probas)
            emotion_labels.append(self.labels[top_result_index])

        return emotion_labels