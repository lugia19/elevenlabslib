from __future__ import annotations
from elevenlabspy.ElevenLabsUser import ElevenLabsUser
from elevenlabspy.helpers import *


class ElevenLabsHistoryItem:
    def __init__(self, data, parentUser):
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
        response = api_get("/history/" + self.historyID + "/audio", self._parentUser.headers)
        return response.content

    def delete(self):
        response = api_del("/history/" + self.historyID, self._parentUser.headers)
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

