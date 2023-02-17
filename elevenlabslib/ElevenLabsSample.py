from __future__ import annotations
from elevenlabslib.ElevenLabsVoice import ElevenLabsVoice
from elevenlabslib.helpers import *

class ElevenLabsSample:
    def __init__(self, sampleData, parentVoice:ElevenLabsVoice):
        self._parentVoice = parentVoice
        self._sampleID = sampleData["sample_id"]
        self._fileName = sampleData["file_name"]
        self._mimeType = sampleData["mime_type"]
        self._size = sampleData["size_bytes"]
        self._hash = sampleData["hash"]

    def get_audio_bytes(self):
        response = api_get("/voices/" + self._parentVoice.voiceID + "/samples/" + self._sampleID + "/audio", self._parentVoice.linkedUser.headers)
        return response.content

    def delete(self):
        response = api_del("/voices/" + self._parentVoice.voiceID + "/samples/" + self._sampleID, self._parentVoice.linkedUser.headers)
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
