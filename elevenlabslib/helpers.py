import io
import logging
from typing import Optional, BinaryIO

import sounddevice as sd
import soundfile
import soundfile as sf
import requests

api_endpoint = "https://api.elevenlabs.io/v1"
default_headers = {'accept': '*/*'}

def _api_call(requestType, path, headers, jsonData=None, filesData=None) -> requests.Response:
    if path[0] != "/":
        path = "/"+path

    if requestType == "get":
        response = requests.get(api_endpoint + path, headers=headers)
    elif requestType == "json":
        response = requests.post(api_endpoint + path, headers=headers, json=jsonData)
    elif requestType == "del":
        response = requests.delete(api_endpoint + path, headers=headers)
    elif requestType == "multipart":
        if filesData is not None:
            response = requests.post(api_endpoint + path, headers=headers, data=jsonData, files=filesData)
        else:
            response = requests.post(api_endpoint + path, headers=headers, data=jsonData)
    else:
        raise ValueError("Unknown API call type!")

    try:
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        _pretty_print_POST(response.request)
        raise e

def _api_get(path, headers) -> requests.Response:
    return _api_call("get",path, headers)

def _api_del(path, headers) -> requests.Response:
    return _api_call("del",path, headers)

def _api_json(path, headers, jsonData) -> requests.Response:
    return _api_call("json",path, headers, jsonData)

def _api_multipart(path, headers, data=None, filesData=None):
    return _api_call("multipart", path, headers, data, filesData)

def _pretty_print_POST(req):
    logging.error('REQUEST THAT CAUSED THE ERROR:\n{}\n{}\r\n{}\r\n\r\n{}'.format(
        '-----------START-----------',
        req.method + ' ' + req.url,
        '\r\n'.join('{}: {}'.format(k, v) for k, v in req.headers.items()),
        req.body,
    ))

def play_audio_bytes(audioData:bytes, playInBackground:bool, portaudioDeviceID:Optional[int] = None) -> None:
    """
    :param audioData: The audio to play
    :param playInBackground: Whether to play it in the background
    :param portaudioDeviceID: The ID of the portaudioDevice to play it back on (Optional)
    :return:
    """
    if portaudioDeviceID is None:
        portaudioDeviceID = sd.default.device
    audioFile = io.BytesIO(audioData)
    soundFile = sf.SoundFile(audioFile)
    sd.play(soundFile.read(), samplerate=soundFile.samplerate, blocking=not playInBackground, device=portaudioDeviceID)

def save_bytes_to_path(filepath:str, audioData:bytes) -> None:
    """
    This function saves the audio data to the specified location.
    soundfile is used for the conversion, so it supports any format it does.
    :param filepath: The path where the data will be saved to.
    :param audioData: The audio data.
    """
    fp = open(filepath, "wb")
    tempSoundFile = soundfile.SoundFile(io.BytesIO(audioData))
    sf.write(fp,tempSoundFile.read(), tempSoundFile.samplerate)

def save_bytes_to_file_object(fp:BinaryIO, audioData:bytes, outputFormat="mp3") -> None:
    """
    This function saves the audio data to the specified file like object, in the specified format.
    soundfile is used for the conversion, so it supports any format it does.
    :param fp: The file-like object the data will be saved to.
    :param audioData: The audio data.
    :param outputFormat: The output format (mp3 by default).
    """
    tempSoundFile = soundfile.SoundFile(io.BytesIO(audioData))
    sf.write(fp,tempSoundFile.read(), tempSoundFile.samplerate, format=outputFormat)