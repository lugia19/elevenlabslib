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
from typing import Optional, BinaryIO, Callable, Union, Any, Iterator, List, AsyncIterator, Tuple, TYPE_CHECKING, TextIO, Dict
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

from elevenlabslib.helpers import SyncIterator, _NumpyRAWStreamer, _NumpyMp3Streamer, _NumpyPlaybacker

# These are hardcoded because they just plain work. If you really want to change them, please be careful.
_playbackBlockSize = 2048
_downloadChunkSize = 4096


from elevenlabslib.Voice import Voice
from elevenlabslib.HistoryItem import HistoryItem
from elevenlabslib.PronunciationDictionary import PronunciationDictionary
from elevenlabslib.Model import Model
from elevenlabslib import *
from elevenlabslib._audio_cutter_helper import split_audio

def play_dialog_with_stitching(voice:Voice, prompts:List[str | Dict[str, str]], generation_options:GenerationOptions = GenerationOptions(), first_prompt_pretext:Optional[str] = None,
                               default_playback_options:PlaybackOptions() = PlaybackOptions(), auto_determine_emotion:bool = False):
    """
    This function generates and plays back a series of audios using request stitching.

    Arguments:
        - voice (Voice): The voice to use
        - prompts (List[str|Dict[str,str]]): The list of texts to be generated, containing either strings or dicts which have both a 'prompt' and a 'next_text', so it can be manually overridden. They can also optionally contain a 'playback_options'.
        - generation_options (GenerationOptions, optional): The GenerationOptions to use.
        - first_prompt_pretext (str, optional): The previous_text to use for the first generation.
        - default_playback_options (PlaybackOptions, optional): The PlaybackOptions to apply to every generation, unless overridden.
        - auto_determine_emotion (bool, optional): Whether to automatically try to determine the emotion of the text, and insert next_text accordingly. Defaults to false.
    """
    #Let's try and determine the overall emotion of the dialog.
    if auto_determine_emotion:
        if isinstance(prompts, dict):
            all_text = " ".join(prompts.values())
        else:
            all_text = " ".join(prompts)
        from elevenlabslib.helpers import get_emotion_for_prompt, emotion_prompts
        dialog_emotion = get_emotion_for_prompt(all_text)
    else:
        dialog_emotion = "neutral"

    previous_generations = []
    prompts_length = len(prompts)
    for idx, prompt in enumerate(prompts):
        stitching_options = StitchingOptions()
        playback_options:PlaybackOptions = default_playback_options
        if idx < prompts_length-1 and not auto_determine_emotion:
            stitching_options.next_text = prompts[idx+1]

        if isinstance(prompt, dict):
            stitching_options.next_text = prompt["next_text"]
            prompt = prompt["prompt"]
            if "playback_options" in prompt:
                playback_options = prompt["playback_options"]
        playback_options.runInBackground = False

        if (stitching_options.next_text is None or stitching_options.next_text == "") and auto_determine_emotion:
            stitching_options.next_text = emotion_prompts[dialog_emotion]

        if idx > 0:
            stitching_options.previous_request_ids = previous_generations[-3:]
        elif first_prompt_pretext:
            stitching_options.previous_text = first_prompt_pretext

        _,_,_, generation_info_future = voice.stream_audio_v3(prompt, generation_options=generation_options, stitching_options=stitching_options)
        generation_info = generation_info_future.result()
        previous_generations.append(generation_info.request_id)

    return


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


class Synthesizer:
    """
    This is a helper class, which allows you to queue up multiple audio generations.

    They will all be downloaded together, and will play back in the same order you put them in. I've found this gives the lowest possible latency.
    """
    def __init__(self, defaultPlaybackOptions:PlaybackOptions=PlaybackOptions(runInBackground=True),
                 defaultGenerationOptions:GenerationOptions=GenerationOptions(latencyOptimizationLevel=3)):
        """
        Initializes the Synthesizer instance.
        Parameters:
            defaultPlaybackOptions (PlaybackOptions, optional): The default playback options (for the onPlayback callbacks), that will be used if none are specified when calling add_to_queue
            defaultGenerationOptions (GenerationOptions, optional): The default generation options, that will be used if none are specified when calling add_to_queue
        """

        self._eventStreamQueue = queue.Queue()
        self._readyForPlaybackEvent = threading.Event()
        self._readyForPlaybackEvent.set()
        self._ttsQueue = queue.Queue()
        self._interruptEvent = threading.Event()
        self._currentStream: sd.OutputStream = None
        self._defaultGenOptions = defaultGenerationOptions
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

    def change_default_settings(self, defaultGenerationOptions:GenerationOptions=None, defaultPlaybackOptions:PlaybackOptions=None):
        """
        Allows you to change the default settings.
        """
        if defaultGenerationOptions is not None:
            self._defaultGenOptions = defaultGenerationOptions
        if defaultPlaybackOptions is not None:
            self._defaultPlayOptions = defaultPlaybackOptions

    def add_to_queue(self, voice:Voice, prompt:str, generationOptions:GenerationOptions=None, playbackOptions:PlaybackOptions = None) -> None:
        """
        Adds an item to the synthesizer queue.
        Parameters:
            voice (Voice): The voice that will speak the prompt
            prompt (str): The prompt to be spoken
            generationOptions (GenerationOptions, optional): Overrides the generation options for this generation
            playbackOptions (PlaybackOptions, optional): Overrides the playback options for this generation
        """
        if generationOptions is None:
            generationOptions = self._defaultGenOptions
        if playbackOptions is None:
            playbackOptions = self._defaultPlayOptions
        self._ttsQueue.put((voice, prompt, generationOptions, playbackOptions))

    def _consumer_thread(self):
        voice, prompt, genOptions, playOptions = None, None, None, None
        while not self._interruptEvent.is_set():
            try:
                voice, prompt, genOptions, playOptions = self._ttsQueue.get(timeout=10)
                playOptions = dataclasses.replace(playOptions, runInBackground=True) #Ensure this is set to true, always.
            except queue.Empty:
                continue
            finally:
                if self._interruptEvent.is_set():
                    logging.debug("Synthetizer consumer loop exiting...")
                    return

            logging.debug(f"Synthesizing prompt: {prompt}")
            self._generate_events_and_begin(voice, prompt, genOptions, playOptions)

    def _generate_events_and_begin(self, voice:Voice, prompt:str, generationOptions:GenerationOptions, playbackOptions:PlaybackOptions):
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

        _, _, streamFuture, _ = voice.stream_audio_v3(prompt=prompt, generation_options=generationOptions, playback_options=wrapped_playbackOptions)
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

            streamer: Union[_NumpyMp3Streamer, _NumpyRAWStreamer]
            temp_future = concurrent.futures.Future()
            temp_future.set_result(current_socket)
            if "mp3" in self._currentGenOptions.output_format:
                streamer = _NumpyMp3Streamer(temp_future, self._currentGenOptions, self._websocketOptions, prompt)
            else:
                streamer = _NumpyRAWStreamer(temp_future, self._currentGenOptions, self._websocketOptions, prompt)

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
            streamer: Union[_NumpyMp3Streamer, _NumpyRAWStreamer]
            temp_future = concurrent.futures.Future()
            temp_future.set_result(current_socket)
            if "mp3" in self._currentGenOptions.output_format:
                streamer = _NumpyMp3Streamer(temp_future, self._currentGenOptions, self._websocketOptions, prompt)
            else:
                streamer = _NumpyRAWStreamer(temp_future, self._currentGenOptions, self._websocketOptions, prompt)

            audio_queue_future.set_result(streamer.playback_queue)
            transcript_queue_future.set_result(streamer.transcript_queue)
            streamer.begin_streaming()
            current_socket.close_socket()
