from __future__ import annotations
from elevenlabslib.ElevenLabsVoice import ElevenLabsVoice
from elevenlabslib.helpers import *
from elevenlabslib.helpers import _api_json,_api_del,_api_get,_api_multipart

class ElevenLabsSample:
    def __init__(self, sampleData, parentVoice:ElevenLabsVoice):
        self._parentVoice = parentVoice
        self._sampleID = sampleData["sample_id"]
        self._fileName = sampleData["file_name"]
        self._mimeType = sampleData["mime_type"]
        self._size = sampleData["size_bytes"]
        self._hash = sampleData["hash"]

    def get_audio_bytes(self):
        """
        Retrieves the audio bytes associated with the sample.

        Returns:
            bytes: a bytes object containing the audio in mp3 format.
        """
        response = _api_get("/voices/" + self._parentVoice.voiceID + "/samples/" + self._sampleID + "/audio", self._parentVoice.linkedUser.headers)
        return response.content

    def play_audio(self, playInBackground: bool, portaudioDeviceID: Optional[int] = None) -> None:
        """
        Plays the audio associated with the sample.

        Args:
            playInBackground: a boolean indicating whether the audio should be played in the background
            portaudioDeviceID: an optional integer representing the portaudio device ID to use
        """
        play_audio_bytes(self.get_audio_bytes(), playInBackground, portaudioDeviceID)
        return

    def delete(self):
        """
        Deletes the sample.
        """
        response = _api_del("/voices/" + self._parentVoice.voiceID + "/samples/" + self._sampleID, self._parentVoice.linkedUser.headers)
        self._sampleID = ""

    @property
    def parentVoice(self):
        return self._parentVoice

    @property
    def sampleID(self):
        return self._sampleID

    @property
    def fileName(self):
        return self._fileName

    @property
    def mimeType(self):
        return self._mimeType

    @property
    def size(self):
        return self._size

    @property
    def hash(self):
        return self._hash
