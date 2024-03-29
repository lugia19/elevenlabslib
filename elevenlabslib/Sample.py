from __future__ import annotations
from elevenlabslib.Voice import Voice
from elevenlabslib.helpers import *
from elevenlabslib.helpers import _api_json, _api_del, _api_get, _api_multipart, _PlayableItem


class Sample(_PlayableItem):
    """
    Represents a sample used for a cloned voice.
    """
    def __init__(self, sampleData, parentVoice: Voice):
        super().__init__()
        self._parentVoice = parentVoice
        self.sampleID = sampleData["sample_id"]
        self.fileName = sampleData["file_name"]
        self._fullMetaData = sampleData
        self._mimeType = sampleData["mime_type"]
        self._size = sampleData["size_bytes"]
        self._hash = sampleData["hash"]

    @property
    def metadata(self):
        """
        The full metadata associated with the sample.
        """
        return self._fullMetaData

    @property
    def parentVoice(self):
        """
        The Voice object associated with this sample.
        """
        return self._parentVoice

    def get_audio_bytes(self) -> bytes:
        return self._fetch_and_cache_audio(lambda: _api_get(f"/voices/{self._parentVoice.voiceID}/samples/{self.sampleID}/audio", self._parentVoice.linkedUser.headers))

    def delete(self):
        """
        Deletes the sample.
        """
        response = _api_del("/voices/" + self._parentVoice.voiceID + "/samples/" + self.sampleID, self._parentVoice.linkedUser.headers)
        self.sampleID = ""


class ElevenLabsSample(Sample):
    def __init__(self, *args, **kwargs):
        warn("This name is deprecated and will be removed in future versions. Use Sample instead.", DeprecationWarning)
        super().__init__(*args, **kwargs)
