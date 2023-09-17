import logging
import queue
import threading
from typing import Optional

from sounddevice import OutputStream

from elevenlabslib import GenerationOptions, PlaybackOptions, ElevenLabsVoice


class Synthesizer:
    def __init__(self, portAudioDeviceID:Optional[int] = None):
        self._eventStreamQueue = queue.Queue()
        self._readyForPlaybackEvent = threading.Event()
        self._readyForPlaybackEvent.set()
        self._outputDeviceIndex = portAudioDeviceID
        self._ttsQueue = queue.Queue()
        self._interruptEvent = threading.Event()
        self._currentStream:OutputStream = None

    def start(self):
        """
        Begins processing the queued audio.
        """
        if self._interruptEvent.is_set():
            raise ValueError("Please do not re-use a Synthesizer instance. Create a new one instead.")

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
        self._currentStream.stop()

    def change_output_device(self, portAudioDeviceID:int):
        """
        Allows you to change the current output device.
        """
        self._outputDeviceIndex = portAudioDeviceID

    def add_to_queue(self, voice:ElevenLabsVoice, prompt:str, generationOptions:GenerationOptions=GenerationOptions(latencyOptimizationLevel=4)) -> None:
        self._ttsQueue.put((voice, prompt, generationOptions))

    def _consumer_thread(self):
        voice, prompt, genOptions = None, None, None
        while True:
            try:
                voice, prompt, genOptions = self._ttsQueue.get(timeout=10)
            except queue.Empty:
                continue
            finally:
                if self._interruptEvent.is_set():
                    logging.debug("Synthetizer consumer loop exiting...")
                    return

            logging.debug(f"Synthesizing prompt: {prompt}")
            self._generate_events(voice, prompt, genOptions)

    def _generate_events(self, voice:ElevenLabsVoice, prompt:str, generationOptions:GenerationOptions):
        newEvent = threading.Event()

        def startcallbackfunc():
            newEvent.wait()
        def endcallbackfunc():
            self._readyForPlaybackEvent.set()

        playbackOptions = PlaybackOptions(runInBackground=True, portaudioDeviceID=self._outputDeviceIndex, onPlaybackStart=startcallbackfunc, onPlaybackEnd=endcallbackfunc)

        _, streamFuture = voice.generate_stream_audio_v2(prompt=prompt, generationOptions=generationOptions, playbackOptions=playbackOptions)
        self._eventStreamQueue.put((newEvent, streamFuture))

    def _ordering_thread(self):
        nextEvent, nextStreamFuture = None, None
        while True:
            self._readyForPlaybackEvent.wait()
            self._readyForPlaybackEvent.clear()
            while True:
                try:
                    nextEvent, nextStreamFuture = self._eventStreamQueue.get(timeout=10)
                except queue.Empty:
                    continue
                finally:
                    if self._interruptEvent.is_set():
                        logging.debug("Synthetizer playback loop exiting...")
                        return
                nextEvent.set()
                self._currentStream = nextStreamFuture.result()
                break