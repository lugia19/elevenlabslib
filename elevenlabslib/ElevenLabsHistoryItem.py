from __future__ import annotations

import requests

from elevenlabslib.ElevenLabsUser import ElevenLabsUser
from elevenlabslib.helpers import *
from elevenlabslib.helpers import _api_json,_api_del,_api_get,_api_multipart


class ElevenLabsHistoryItem:
    """
    Represents a previously generated audio.

    Tip:
        There is no method to get an ElevenLabsVoice object for the voice that was used to create the file as it may not exist anymore.
        You can use the voiceID for that.
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
        self._settingsUsed = data["settings"]
        self._fullMetadata = data
        self._fullMetadata.pop("feedback")  #We don't want to expose the initial feedbackData, as that can change.
        self._audioData = None

    @property
    def metadata(self):
        """
        All the metadata associated with the item.
        """
        return self._fullMetadata

    @property
    def settings_used(self):
        """
        The settings used for this generation.
        """
        return self._settingsUsed

    @property
    def historyID(self):
        """
        The ID of the history item.
        """
        return self._historyID

    @property
    def parentUser(self):
        """
        The ElevenLabsUser object for the user that generated this item.
        """
        return self._parentUser

    @property
    def voiceId(self):
        """
        The voiceID of the voice used.
        """
        return self._voiceId

    @property
    def voiceName(self):
        """
        The name of the voice used.
        """
        return self._voiceName

    @property
    def text(self):
        """
        The text of the item.
        """
        return self._text

    @property
    def characterCountChangeFrom(self):
        return self._characterCountChangeFrom

    @property
    def characterCountChangeTo(self):
        return self._characterCountChangeTo

    @property
    def characterCountChangeAmount(self):
        """
        How many characters this generation used.
        """
        return self._characterCountChangeTo - self._characterCountChangeFrom

    def get_audio_bytes(self) -> bytes:
        """
        Retrieves the audio bytes associated with the history item.

        Note:
            The audio will be cached so that it's not downloaded every time this is called.

        Caution:
            If you're looking to download multiple history items, use ElevenLabsUser.download_history_items() instead.
            That will call a different endpoint, optimized for multiple downloads.

        Returns:
            bytes: The bytes of the mp3 file.
        """
        if self._audioData is None:
            response = _api_get("/history/" + self.historyID + "/audio", self._parentUser.headers)
            self._audioData = response.content
        return self._audioData

    def play_audio(self, playInBackground: bool, portaudioDeviceID: Optional[int] = None,
                     onPlaybackStart:Callable=lambda: None, onPlaybackEnd:Callable=lambda: None) -> None:
        """
        Plays the audio associated with the history item.

        Args:
            playInBackground: a boolean indicating whether the audio should be played in the background
            portaudioDeviceID: an optional integer representing the portaudio device ID to use
            onPlaybackStart: Function to call once the playback begins
            onPlaybackEnd: Function to call once the playback ends
        """
        play_audio_bytes(self.get_audio_bytes(), playInBackground, portaudioDeviceID, onPlaybackStart, onPlaybackEnd)
        return

    def fetch_feedback(self):
        """
        Fetches the feedback information associated with this generation.
        """
        response = _api_get(f"/history/{self.historyID}", headers=self._parentUser.headers)
        return response.json()["feedback"]

    def edit_feedback(self, thumbsUp:bool, feedbackText:str="", issueTypes:list[str] = None):
        """
        Allows you to leave feedback for this generation.

        Args:
            thumbsUp: Whether or not to rate the generation positively.
            feedbackText: Any text you'd like to add as feedback. Only sent if thumbsUp is true, in which case it must be at least 50 characters.
            issueTypes: A list of types of issues this generation falls under. Only sent if thumbsUp is false.
            The valid values are: emotions, inaccurate_clone, glitches, audio_quality, other. Other values will be ignored.
        """
        payload = {
            "thumbs_up":thumbsUp,
            "feedback":""
        }

        validIssueTypes = ["emotions", "inaccurate_clone", "glitches", "audio_quality", "other"]
        for issueType in validIssueTypes:
            if issueTypes and issueType in issueTypes and not thumbsUp:
                payload[issueType] = True
            else:
                payload[issueType] = False

        if thumbsUp:
            if len(feedbackText) < 50:
                raise ValueError("Error! Positive feedback text must be at least 50 characters!")
            payload["feedback"] = feedbackText

        response = _api_json(f"/history/{self.historyID}/feedback", headers=self._parentUser.headers, jsonData=payload)
        return response

    def delete(self):
        """
        Deletes the item from your history.
        """
        response = _api_del("/history/" + self.historyID, self._parentUser.headers)
        self._historyID = ""



