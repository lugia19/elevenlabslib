import dataclasses
import io
import logging
import queue
import threading
import time
from typing import Optional, BinaryIO, Callable, Union, Any
from warnings import warn

import sounddevice as sd
import soundfile
import soundfile as sf
import requests
import os

from elevenlabslib.ElevenLabsModel import ElevenLabsModel

api_endpoint = "https://api.elevenlabs.io/v1"
default_headers = {'accept': '*/*'}

def _api_call_v2(requestMethod, argsDict) -> requests.Response:
    path = argsDict["path"]
    if path[0] != "/":
        path = "/"+path
    argsDict["url"] = api_endpoint + path
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

def _api_multipart(path, headers, data, filesData=None, stream=False, params=None):
    args = {
        "path":path,
        "headers":headers,
        "stream":stream,
        "data":data
    }
    if filesData is not None:
        args["files"] = filesData
    if params is not None:
        args["params"] = params

    return _api_call_v2(requests.post, args)

def _pretty_print_POST(res:requests.Response):
    req = res.request
    import logging
    logging.basicConfig(level=logging.DEBUG)
    logging.error(f"RESPONSE DATA: {res.text}")
    logging.error('REQUEST THAT CAUSED THE ERROR:\n{}\n{}\r\n{}\r\n\r\n{}'.format(
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
        runInBackground (bool): Whether to play/stream audio in the background or wait for it to finish playing.
        portaudioDeviceID (int, optional): The ID of the audio device to use for playback. Defaults to the default output device.
        onPlaybackStart (Callable, optional): Function to call once the playback begins.
        onPlaybackEnd (Callable, optional): Function to call once the playback ends.
    """
    runInBackground: bool
    portaudioDeviceID: Optional[int] = None
    onPlaybackStart: Callable[[], Any] = lambda: None
    onPlaybackEnd: Callable[[], Any] = lambda: None

@dataclasses.dataclass
class GenerationOptions:
    """
    This class holds the options for TTS generation.
    If any option besides model_id and latencyOptimizationLevel is omitted, the stored value associated with the voice is used.

    Parameters:
        model (ElevenLabsModel|str, optional): The TTS model (or its ID) to use for the generation. Defaults to monolingual english v1.
        latencyOptimizationLevel (int, optional): The level of latency optimization (0-4) to apply. Defaults to 0.
        stability (float, optional): A float between 0 and 1 representing the stability of the generated audio. If omitted, the current stability setting is used.
        similarity_boost (float, optional): A float between 0 and 1 representing the similarity boost of the generated audio. If omitted, the current similarity boost setting is used.
        style (float, optional): A float between 0 and 1 representing how much focus should be placed on the text vs the associated audio data for the voice's style, with 0 being all text and 1 being all audio.
        use_speaker_boost (bool, optional): Boost the similarity of the synthesized speech and the voice at the cost of some generation speed.

    Note:
        The latencyOptimizationLevel ranges from 0 to 4. Each level trades off some more quality for speed.

        The levels are as follows:
            - 0: Normal, no optimizations applied
            - 1: 50% of possible latency optimization
            - 2: 75% of possible latency optimization
            - 3: 100% of possible latency optimization
            - 4: 100% + text normalizer disabled (best latency but can mispronounce numbers/dates)

    Warning:
        The style and use_speaker_boost parameters are only available on v2 models, and will be ignored for v1 models.

        Setting style to higher than 0 and enabling use_speaker_boost will both increase latency.

    """
    latencyOptimizationLevel: int = 0
    stability: Optional[float] = None
    similarity_boost: Optional[float] = None
    style: Optional[float] = None
    use_speaker_boost: Optional[bool] = None
    model: Optional[Union[ElevenLabsModel, str]] = "eleven_monolingual_v1"
    model_id: Optional[str] = dataclasses.field(default=None, init=True, repr=False)
    def __post_init__(self):
        if self.model_id:
            self.model = self.model_id
        if not self.model_id:
            if isinstance(self.model, str):
                self.model_id = self.model
            else:
                self.model_id = self.model.modelID


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

def play_audio_bytes(audioData:bytes, playInBackground:bool, portaudioDeviceID:Optional[int] = None,
                     onPlaybackStart:Callable=lambda: None, onPlaybackEnd:Callable=lambda: None) -> sd.OutputStream:
    warn("This function is deprecated. Please use play_audio_bytes_v2 instead. See the porting guide on https://elevenlabslib.readthedocs.io for more information.", DeprecationWarning)

    return play_audio_bytes_v2(audioData, PlaybackOptions(playInBackground, portaudioDeviceID, onPlaybackStart, onPlaybackEnd))

def play_audio_bytes_v2(audioData:bytes, playbackOptions:PlaybackOptions) -> sd.OutputStream:
    """
        Plays the given audio and calls the given functions.

        Parameters:
             audioData: The audio data to play
             playbackOptions: The playback options.

        Returns:
            None
        """

    # Let's make sure the user didn't just forward a tuple from one of the other functions...
    if isinstance(audioData, tuple):
        for item in audioData:
            if isinstance(item, bytes):
                audioData = item

    playbackWrapper = _SDPlaybackWrapper(audioData, playbackOptions)

    if not playbackOptions.runInBackground:
        with playbackWrapper.stream:
            playbackWrapper.endPlaybackEvent.wait()
    else:
        playbackWrapper.stream.start()
        return playbackWrapper.stream

def save_audio_bytes(audioData:bytes, saveLocation:Union[BinaryIO,str], outputFormat) -> None:
    """
    This function saves the audio data to the specified location OR file-like object.
    soundfile is used for the conversion, so it supports any format it does.

    Parameters:
        audioData: The audio data.
        saveLocation: The path (or file-like object) where the data will be saved.
        outputFormat: The format in which the audio will be saved
    """

    # Let's make sure the user didn't just forward a tuple from one of the other functions...
    if isinstance(audioData, tuple):
        for item in audioData:
            if isinstance(item, bytes):
                audioData = item

    tempSoundFile = soundfile.SoundFile(io.BytesIO(audioData))

    if isinstance(saveLocation, str):
        with open(saveLocation, "wb") as fp:
            sf.write(fp, tempSoundFile.read(), tempSoundFile.samplerate, format=outputFormat)
    else:
        sf.write(saveLocation, tempSoundFile.read(), tempSoundFile.samplerate, format=outputFormat)
        if callable(getattr(saveLocation,"flush")):
            saveLocation.flush()

#This class just helps with the callback stuff.
class _SDPlaybackWrapper:
    def __init__(self, audioData:bytes, playbackOptions:PlaybackOptions):
        soundFile = sf.SoundFile(io.BytesIO(audioData))
        soundFile.seek(0)
        self.onPlaybackStart = playbackOptions.onPlaybackStart
        self.onPlaybackEnd = playbackOptions.onPlaybackEnd
        self.startPlaybackEvent = threading.Event()
        self.endPlaybackEvent = threading.Event()
        self.data = soundFile.read(always_2d=True)
        self.currentFrame = 0
        self.stream = sd.OutputStream(channels=soundFile.channels,
            callback=self.callback,
            samplerate=soundFile.samplerate,
            device=playbackOptions.portaudioDeviceID or sd.default.device,
            finished_callback=self.end_playback)

    def callback(self, outdata, frames, time, status):
        if status:
            print(status)

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

class PeekQueue(queue.Queue):
    def peek(self):
        with self.mutex:
            return list(self.queue)[0]

    def snapshot(self):
        with self.mutex:
            return list(self.queue)


def _api_tts_with_concurrency(requestFunction:callable, generationID:str, generationQueue:PeekQueue) -> requests.Response:
    #Just a helper function which does all the concurrency stupidity for TTS calls.
    waitMultiplier = 1
    try:
        response = requestFunction()
        response.raise_for_status() #Just in case the callable isn't a function that already does this.
    except requests.exceptions.RequestException as e:
        if e.response.json()["detail"]["status"] == "too_many_concurrent_requests":
            logging.warning(f"{generationID} - broke concurrency limits, handling the cooldown...")
            # Insert this in the user's "waiting to be generated" queue.
            generationQueue.put(generationID)
            response = None
        else:
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
                    logging.debug(f"\nOther items are first in queue, waiting for 0.3s\n")
                    time.sleep(0.5)  # The time to peek at the queue is constant.
            except requests.exceptions.RequestException as e:
                if e.response.json()["detail"]["status"] == "too_many_concurrent_requests":
                    logging.debug(f"\nWaiting for {0.5 * waitMultiplier}s\n")
                    time.sleep(0.5 * waitMultiplier)  # Just wait a moment and try again.
                    waitMultiplier += 1
                    continue
                raise e

    return response
