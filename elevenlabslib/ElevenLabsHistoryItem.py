from __future__ import annotations
from elevenlabslib.ElevenLabsUser import ElevenLabsUser
from elevenlabslib.helpers import *
from elevenlabslib.helpers import _api_json,_api_del,_api_get,_api_multipart


class ElevenLabsHistoryItem:
    """
    Represents a previously generated audio.
    """
    def __init__(self, data:dict, parentUser:ElevenLabsUser):
        """
        Initializes a new instance of the ElevenLabsHistoryItem class.

        Args:
        	data: a dictionary containing information about the history item
        	parentUser: an instance of ElevenLabsUser class representing the user that generated it
        """
        self._parentUser:ElevenLabsUser = parentUser
        self._historyID = data["history_item_id"]
        self._voiceId = data["voice_id"]
        self._voiceName = data["voice_name"]
        self._text = data["text"]
        self._dateUnix = data["date_unix"]
        self._characterCountChangeFrom = data["character_count_change_from"]
        self._characterCountChangeTo = data["character_count_change_to"]
        self._contentType = data["content_type"]
        self._state = data["state"]

    def get_audio_bytes(self):
        """
        Retrieves the audio bytes associated with the history item.
        IMPORTANT: If you're looking to download multiple history items, use the user function instead.
        That will download a zip containing all the history items (by calling a different endpoint).

        Returns:
            bytes: a bytes object containing the audio in mp3 format.
        """
        response = _api_get("/history/" + self.historyID + "/audio", self._parentUser.headers)
        return response.content

    def play_audio(self, playInBackground: bool, portaudioDeviceID: Optional[int] = None) -> None:
        """
        Plays the audio associated with the history item.

        Args:
            playInBackground: a boolean indicating whether the audio should be played in the background
            portaudioDeviceID: an optional integer representing the portaudio device ID to use
        """
        play_audio_bytes(self.get_audio_bytes(), playInBackground, portaudioDeviceID)
        return

    def delete(self):
        """
        Deletes the history item.
        """
        response = _api_del("/history/" + self.historyID, self._parentUser.headers)
        self._historyID = ""

    @property
    def historyID(self):
        return self._historyID

    @property
    def parentUser(self):
        return self._parentUser

    #There is no method to get the original voice as an object because it might not exist anymore.
    @property
    def voiceId(self):
        return self._voiceId

    @property
    def voiceName(self):
        return self._voiceName

    @property
    def text(self):
        return self._text

    @property
    def dateUnix(self):
        return self._dateUnix

    @property
    def characterCountChangeFrom(self):
        return self._characterCountChangeFrom

    @property
    def characterCountChangeTo(self):
        return self._characterCountChangeTo

    @property
    def characterCountChangeAmount(self):
        return self._characterCountChangeTo-self._characterCountChangeFrom

    @property
    def contentType(self):
        return self._contentType

    @property
    def state(self):
        return self._state

