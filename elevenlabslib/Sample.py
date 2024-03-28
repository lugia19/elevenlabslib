from __future__ import annotations
from elevenlabslib.Voice import Voice
from elevenlabslib.helpers import *
from elevenlabslib.helpers import _api_json,_api_del,_api_get,_api_multipart

class Sample:
    """
    Represents a sample used for a cloned voice.
    """
    def __init__(self, sampleData, parentVoice:Voice):
        self._parentVoice = parentVoice
        self.sampleID = sampleData["sample_id"]
        self.fileName = sampleData["file_name"]
        self._fullMetaData = sampleData
        self._mimeType = sampleData["mime_type"]
        self._size = sampleData["size_bytes"]
        self._hash = sampleData["hash"]
        self._audioData = None      #This is used to cache the audio data since it never changes.

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
        """
        Retrieves the audio bytes associated with the sample.

        Note:
            The audio will be cached so that it's not downloaded every time this is called.

        Returns:
            bytes: a bytes object containing the audio in whatever format it was originally uploaded in.
        """
        if self._audioData is None:
            response = _api_get("/voices/" + self._parentVoice.voiceID + "/samples/" + self.sampleID + "/audio", self._parentVoice.linkedUser.headers)
            self._audioData = response.content
        return self._audioData

    def play_audio(self, playInBackground: bool, portaudioDeviceID: Optional[int] = None,
                     onPlaybackStart:Callable=lambda: None, onPlaybackEnd:Callable=lambda: None) -> sd.OutputStream:
        warn("This function is outdated. Please use play_audio_v2() instead.", DeprecationWarning)
        return self.play_audio_v2(PlaybackOptions(playInBackground, portaudioDeviceID, onPlaybackStart, onPlaybackEnd))

    def play_audio_v2(self, playbackOptions:PlaybackOptions) -> sd.OutputStream:
        """
        Plays the audio associated with the sample.

        Args:
            playbackOptions (PlaybackOptions): Options for the audio playback such as the device to use and whether to run in the background.
        Returns:
            The sounddevice OutputStream of the playback.
        """
        return play_audio_v2(self.get_audio_bytes(), playbackOptions)

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
