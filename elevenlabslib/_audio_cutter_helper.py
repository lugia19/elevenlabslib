#Most of this code is taken and adapted from https://github.com/snakers4/silero-vad, just changed to not rely on pytorch.

import io
import logging
import threading
import soundfile as sf
import appdirs
import requests
import os

from typing import Callable, BinaryIO, Union
import warnings
import numpy as np
import resampy

_silero_model = None
_silero_model_lock = threading.Lock()
class _OnnxWrapper:
    def __init__(self, path, force_onnx_cpu=False):
        import onnxruntime
        onnxruntime.set_default_logger_severity(3)
        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1

        if force_onnx_cpu and 'CPUExecutionProvider' in onnxruntime.get_available_providers():
            self.session = onnxruntime.InferenceSession(path, providers=['CPUExecutionProvider'], sess_options=opts)
        else:
            self.session = onnxruntime.InferenceSession(path, sess_options=opts)

        self.reset_states()
        self.sample_rates = [8000, 16000]

    def _validate_input(self, x:np.ndarray, sr: int):
        if x.ndim == 1:
            x = np.expand_dims(x, 0)
        if x.ndim > 2:
            raise ValueError(f"Too many dimensions for input audio chunk {x.ndim}")

        if sr != 16000 and (sr % 16000 == 0):
            step = sr // 16000
            x = x[:,::step]
            sr = 16000

        if sr not in self.sample_rates:
            raise ValueError(f"Supported sampling rates: {self.sample_rates} (or multiply of 16000)")

        if sr / x.shape[1] > 31.25:
            raise ValueError("Input audio chunk is too short")

        return x, sr

    def reset_states(self, batch_size=1):
        self._h = np.zeros((2, batch_size, 64)).astype('float32')
        self._c = np.zeros((2, batch_size, 64)).astype('float32')
        self._last_sr = 0
        self._last_batch_size = 0

    def __call__(self, x:np.ndarray, sr: int):

        x, sr = self._validate_input(x, sr)
        batch_size = x.shape[0]

        if not self._last_batch_size:
            self.reset_states(batch_size)
        if (self._last_sr) and (self._last_sr != sr):
            self.reset_states(batch_size)
        if (self._last_batch_size) and (self._last_batch_size != batch_size):
            self.reset_states(batch_size)

        if sr in [8000, 16000]:
            ort_inputs = {'input': x.astype(np.float32), 'h': self._h, 'c': self._c, 'sr': np.array(sr, dtype='int64')}
            ort_outs = self.session.run(None, ort_inputs)
            out, self._h, self._c = ort_outs
        else:
            raise ValueError()

        self._last_sr = sr
        self._last_batch_size = batch_size

        return out

    def audio_forward(self, x:np.ndarray, sr: int, num_samples: int = 512):
        outs = []
        x, sr = self._validate_input(x, sr)

        if x.shape[1] % num_samples:
            pad_num = num_samples - (x.shape[1] % num_samples)
            x = np.pad(x, ((0, 0), (0, pad_num)), mode='constant', constant_values=0.0)

        self.reset_states(x.shape[0])
        for i in range(0, x.shape[1], num_samples):
            wavs_batch = x[:, i:i+num_samples]
            out_chunk = self.__call__(wavs_batch, sr)
            outs.append(out_chunk)

        stacked = np.concatenate(outs, axis=1)
        return stacked

def _get_speech_timestamps(audio: np.ndarray,
                           threshold: float = 0.5,
                           sampling_rate: int = 16000,
                           min_speech_duration_ms: int = 250,
                           max_speech_duration_s: float = float('inf'),
                           min_silence_duration_ms: int = 100,
                           window_size_samples: int = 512,
                           speech_pad_ms: int = 30,
                           return_seconds: bool = False,
                           progress_tracking_callback: Callable[[float], None] = None):
    model = _get_silero_model()

    if len(audio.shape) > 1:
        for i in range(len(audio.shape)):  # trying to squeeze empty dimensions
            audio = audio.squeeze(0)
        if len(audio.shape) > 1:
            raise ValueError("More than one dimension in audio. Are you trying to process audio with 2 channels?")

    if sampling_rate > 16000 and (sampling_rate % 16000 == 0):
        step = sampling_rate // 16000
        sampling_rate = 16000
        audio = audio[::step]
        logging.debug('Sampling rate is a multiply of 16000, casting to 16000 manually!')
    else:
        step = 1

    if sampling_rate == 8000 and window_size_samples > 768:
        logging.warning('window_size_samples is too big for 8000 sampling_rate! Better set window_size_samples to 256, 512 or 768 for 8000 sample rate!')
    if window_size_samples not in [256, 512, 768, 1024, 1536]:
        logging.warning('Unusual window_size_samples! Supported window_size_samples:\n - [512, 1024, 1536] for 16000 sampling_rate\n - [256, 512, 768] for 8000 sampling_rate')

    model.reset_states()
    min_speech_samples = sampling_rate * min_speech_duration_ms / 1000
    speech_pad_samples = sampling_rate * speech_pad_ms / 1000
    max_speech_samples = sampling_rate * max_speech_duration_s - window_size_samples - 2 * speech_pad_samples
    min_silence_samples = sampling_rate * min_silence_duration_ms / 1000
    min_silence_samples_at_max_speech = sampling_rate * 98 / 1000

    audio_length_samples = len(audio)

    speech_probs = []
    for current_start_sample in range(0, audio_length_samples, window_size_samples):
        chunk = audio[current_start_sample: current_start_sample + window_size_samples]
        if len(chunk) < window_size_samples:
            chunk = np.pad(chunk, (0, int(window_size_samples - len(chunk))), mode='constant', constant_values=(0, 0))

        speech_prob = model(chunk, sampling_rate).item()
        speech_probs.append(speech_prob)
        # caculate progress and seng it to callback function
        progress = current_start_sample + window_size_samples
        if progress > audio_length_samples:
            progress = audio_length_samples
        progress_percent = (progress / audio_length_samples) * 100
        if progress_tracking_callback:
            progress_tracking_callback(progress_percent)

    triggered = False
    speeches = []
    current_speech = {}
    neg_threshold = threshold - 0.15
    temp_end = 0 # to save potential segment end (and tolerate some silence)
    prev_end = next_start = 0 # to save potential segment limits in case of maximum segment size reached

    for i, speech_prob in enumerate(speech_probs):
        if (speech_prob >= threshold) and temp_end:
            temp_end = 0
            if next_start < prev_end:
               next_start = window_size_samples * i

        if (speech_prob >= threshold) and not triggered:
            triggered = True
            current_speech['start'] = window_size_samples * i
            continue

        if triggered and (window_size_samples * i) - current_speech['start'] > max_speech_samples:
            if prev_end:
                current_speech['end'] = prev_end
                speeches.append(current_speech)
                current_speech = {}
                if next_start < prev_end: # previously reached silence (< neg_thres) and is still not speech (< thres)
                    triggered = False
                else:
                    current_speech['start'] = next_start
                prev_end = next_start = temp_end = 0
            else:
                current_speech['end'] = window_size_samples * i
                speeches.append(current_speech)
                current_speech = {}
                prev_end = next_start = temp_end = 0
                triggered = False
                continue

        if (speech_prob < neg_threshold) and triggered:
            if not temp_end:
                temp_end = window_size_samples * i
            if ((window_size_samples * i) - temp_end) > min_silence_samples_at_max_speech : # condition to avoid cutting in very short silence
                prev_end = temp_end
            if (window_size_samples * i) - temp_end < min_silence_samples:
                continue
            else:
                current_speech['end'] = temp_end
                if (current_speech['end'] - current_speech['start']) > min_speech_samples:
                    speeches.append(current_speech)
                current_speech = {}
                prev_end = next_start = temp_end = 0
                triggered = False
                continue

    if current_speech and (audio_length_samples - current_speech['start']) > min_speech_samples:
        current_speech['end'] = audio_length_samples
        speeches.append(current_speech)

    for i, speech in enumerate(speeches):
        if i == 0:
            speech['start'] = int(max(0, speech['start'] - speech_pad_samples))
        if i != len(speeches) - 1:
            silence_duration = speeches[i+1]['start'] - speech['end']
            if silence_duration < 2 * speech_pad_samples:
                speech['end'] += int(silence_duration // 2)
                speeches[i+1]['start'] = int(max(0, speeches[i+1]['start'] - silence_duration // 2))
            else:
                speech['end'] = int(min(audio_length_samples, speech['end'] + speech_pad_samples))
                speeches[i+1]['start'] = int(max(0, speeches[i+1]['start'] - speech_pad_samples))
        else:
            speech['end'] = int(min(audio_length_samples, speech['end'] + speech_pad_samples))

    if return_seconds:
        for speech_dict in speeches:
            speech_dict['start'] = round(speech_dict['start'] / sampling_rate, 1)
            speech_dict['end'] = round(speech_dict['end'] / sampling_rate, 1)
    elif step > 1:
        for speech_dict in speeches:
            speech_dict['start'] *= step
            speech_dict['end'] *= step


    return speeches


def _download_onnx_model(model_url):
    # Define the cache directory and ensure it exists
    cache_dir = appdirs.user_cache_dir("elevenlabslib", "lugia19")
    os.makedirs(cache_dir, exist_ok=True)

    # Define the path to the model and the lock file
    model_path = os.path.join(cache_dir, "silero_vad.onnx")
    lock_file_path = model_path + ".lock"

    # Check if the model already exists
    if os.path.exists(model_path):
        logging.debug(f"Silero model already downloaded at {model_path}")
        return model_path

    # If the lock file exists, assume the download was interrupted
    if os.path.exists(lock_file_path):
        logging.debug("Previous download was interrupted. Restarting download.")
        os.remove(lock_file_path)  # Clean up lock file from interrupted download

    # Create a lock file to indicate the download is in progress
    with open(lock_file_path, 'w') as lock_file:
        lock_file.write("")

    try:
        # Download the model
        logging.debug(f"Downloading silero VAD model to {model_path}")
        response = requests.get(model_url)
        response.raise_for_status()  # Ensure we notice bad responses

        # Write the downloaded model to the file
        with open(model_path, 'wb') as model_file:
            model_file.write(response.content)
        logging.debug(f"Model downloaded successfully to {model_path}")
    except Exception as e:
        logging.error(f"Failed to download the model: {e}")
        # Remove the model file if it exists to prevent partial files
        if os.path.exists(model_path):
            os.remove(model_path)
        raise
    finally:
        # Remove the lock file once the download is complete or failed
        if os.path.exists(lock_file_path):
            os.remove(lock_file_path)

    return model_path

def _get_silero_model(force_onnx_cpu=False):
    global _silero_model
    with _silero_model_lock:
        if _silero_model is None:
            model_url = "https://github.com/snakers4/silero-vad/raw/master/files/silero_vad.onnx"
            model_path = _download_onnx_model(model_url)
            _silero_model = _OnnxWrapper(model_path, force_onnx_cpu)
    return _silero_model

def _cut_audio_at_breakpoints(audio_bytes, timestamps, segment_duration_s):
    data, samplerate = sf.read(io.BytesIO(audio_bytes), always_2d=True)
    segments = []

    previous_section_end = 0

    for idx, timestamp in enumerate(timestamps):
        if timestamp['end'] - timestamp['start'] > segment_duration_s:
            raise RuntimeError("Audio has speech segment longer than 5 minutes. Aborting.")

        if timestamp['end'] > previous_section_end + segment_duration_s:
            # Extract and save up to the current point
            previous_segment = timestamps[idx-1]
            segment_data = data[int(previous_section_end*samplerate):int(previous_segment["end"]*samplerate)]
            temp_io = io.BytesIO()
            sf.write(temp_io, segment_data, samplerate, format="wav")
            segments.append(temp_io)
            # Update the end for the next segment
            previous_section_end = previous_segment['end']


    # After processing all timestamps, check if there's a remaining section to be saved
    if previous_section_end < timestamps[-1]["end"]:
        segment_data = data[int(previous_section_end*samplerate):]
        temp_io = io.BytesIO()
        sf.write(temp_io, segment_data, samplerate, format="wav")
        segments.append(temp_io)

    for temp_io in segments:
        temp_io.seek(0)
    return segments


def split_audio(audio_data:Union[bytes, BinaryIO], speech_threshold:float=0.5, segment_duration_s:int=295) -> list[io.BytesIO]:
    """
    Splits the given audio_data (must be in bytes, or a file pointer) into segments.

    Parameters:
        audio_data (bytes|BinaryIO): The audio to split, in bytes.
        speech_threshold (float): The likelyhood that a segment must be speech for it to be recognized (0.5/50% works for most datasets).
        segment_duration_s (int): How long the returned segments must be. Defaults to 295 for speech to speech.

    Returns:
        list[io.BytesIO]: A list of BytesIO containing wav files, all shorter than segment_duration_s.
    """
    #Splits the given audio_data into segments, returned as a list of BytesIO objects containing wav files.

    #Get the timestamps:
    data, samplerate = sf.read(io.BytesIO(audio_data))
    duration = len(data) / samplerate
    if duration < 300:
        return [io.BytesIO(audio_data)] #Shorter than 5 minutes, just return the audio itself.

    #Audio is longer than 5 minutes, let's prepare it...
    #Flatten the data if it's stereo
    if data.ndim == 2:
        data = data.mean(axis=1)

    #Check if sample rate is not a multiple of 16000
    if samplerate % 16000 != 0:
        data = resampy.resample(data, samplerate, 16000)
        samplerate = 16000

    #Audio is now mono and a multiple of 16000 Hz. Send it to silero.
    timestamps = _get_speech_timestamps(data, sampling_rate=samplerate, threshold=speech_threshold, return_seconds=True, max_speech_duration_s=segment_duration_s)

    audio_bytesios = _cut_audio_at_breakpoints(audio_data, timestamps, segment_duration_s=segment_duration_s)
    return audio_bytesios


