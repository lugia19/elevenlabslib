from __future__ import annotations

from datetime import datetime

import requests

from elevenlabslib.ElevenLabsUser import ElevenLabsUser
from elevenlabslib.helpers import *
from elevenlabslib.helpers import _api_json,_api_del,_api_get,_api_multipart, _audio_is_raw

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
        self._voiceCategory = data["voice_category"]
        self._model = data["model_id"]
        self._text = data["text"]
        self._dateUnix = data["date_unix"]
        self._characterCountChangeFrom = data["character_count_change_from"]
        self._characterCountChangeTo = data["character_count_change_to"]
        self._settingsUsed = data["settings"]
        self._fullMetadata = data
        self._audioData = None

    @property
    def metadata(self):
        """
        All the metadata associated with the item.
        """
        return self._fullMetadata

    @property
    def settings_used(self):
        warn("This is deprecated in favor of generation_settings, which returns a GenerationOptions object instead.", DeprecationWarning)
        return self._settingsUsed

    @property
    def generation_settings(self):
        """
        The settings used for this generation, as a GenerationOptions object.

        Warning:
            The following properties will be missing/invalid in the returned GenerationOptions due to the API not providing them:
                - latencyOptimizationLevel will be set to -99
        """
        return GenerationOptions(model=self._model,
                                 stability=self._settingsUsed.get("stability"),
                                 similarity_boost=self._settingsUsed.get("similarity_boost"),
                                 style=self._settingsUsed.get("style"),
                                 use_speaker_boost=self._settingsUsed.get("use_speaker_boost"),
                                 latencyOptimizationLevel=-99)
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
    def voiceCategory(self):
        """
        The type of voice used.
        """
        return self._voiceCategory

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

    @property
    def timestamp(self):
        return datetime.utcfromtimestamp(self._dateUnix)

    # Filenames are constructed as follows:
    # Prefix: ElevenLabs_
    # Date: 2023-09-22
    # Time: T12_13_50 (UTC)     NOTE: There is a discrepancy. Downloading through the site puts spaces, the API puts underscores.
    # Voice Name: Rachel Test
    # Category: ivc/pre/pvc/gen, depending on category.
    # Stability, SimilarityBoost, StyleExaggeration and Boost: s30_sb95_se20_b  (b is either present or not present, depending on whether boost was used.)
    # Model indicator: e1, e2, m1, m2.
    # Extension: always .mp3, even for PCM audio. Bug.

    # Most of these are easy. The abbreviations seem like they're just hardcoded.
    @property
    def filename(self):
        """
        The filename the audio will have.

        Note:
            There is a discrepancy in the timestamp. When returned through the website, they have spaces. In the API, they have underscores.
        """
        dt = self.timestamp
        date_string = dt.strftime('%Y-%m-%d')
        time_string = dt.strftime('%H_%M_%S')
        category_string = category_shorthands.get(self.voiceCategory)

        genSettings = self.generation_settings
        settings_string = f"s{round(genSettings.stability*100)}_sb{round(genSettings.similarity_boost*100)}"
        if "v2" in genSettings.model_id:
            settings_string += f"_se{round(genSettings.style*100)}{'_b' if genSettings.use_speaker_boost else ''}"

        model_string = model_shorthands.get(genSettings.model_id)
        filename = f"ElevenLabs_{date_string}T{time_string}_{self.voiceName}_{category_string}_{settings_string}_{model_string}"

        #This is just here to be implemented in the future. Right now, both PCM and mp3 audio get a .mp3 extension on the API.
        #TODO: Change this once it's fixed.
        filename += ".mp3"
        #if _audio_is_pcm(self._audioData):
        #    extension = ".mp3"
        #else:
        #    extension = ".mp3"

        return filename

    def get_audio_bytes(self) -> bytes:
        """
        Retrieves the audio bytes associated with the history item.

        Note:
            The audio will be cached so that it's not downloaded every time this is called.

        Error:
            The history currently saves PCM generations directly, without any header data.
            Since the samplerate isn't saved either, you'll basically just need to guess which samplerate it is if trying to play it back.
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
                     onPlaybackStart:Callable=lambda: None, onPlaybackEnd:Callable=lambda: None) -> sd.OutputStream:
        warn("This function is outdated. Please use play_audio_v2() instead.", DeprecationWarning)
        return self.play_audio_v2(PlaybackOptions(playInBackground, portaudioDeviceID, onPlaybackStart, onPlaybackEnd))

    def play_audio_v2(self, playbackOptions:PlaybackOptions) -> sd.OutputStream:
        """
        Plays the audio associated with the history item.

        Args:
            playbackOptions (PlaybackOptions): Options for the audio playback such as the device to use and whether to run in the background.
        Returns:
            The sounddevice OutputStream of the playback.

        Error:
            Due to the lack of samplerate information, when playing back a generation created with PCM, the library assumes it was made using the highest samplerate available to your account.
            Additionally, we're assuming the file is using PCM rather than ULAW.

            If either of the above assumptions isn't true, simply use the audio functions in helpers.py to play back the audio yourself.
        """
        audioBytes = self.get_audio_bytes()
        output_format = "mp3_44100_128"
        if _audio_is_raw(audioBytes):
            output_format = self._parentUser.get_real_audio_format(GenerationOptions(output_format="pcm_highest")).output_format

        return play_audio_v2(audioBytes, playbackOptions, output_format)

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

        Note:
            The valid values for issueTypes are: emotions, inaccurate_clone, glitches, audio_quality, other

            Other values will be ignored.

        Caution:
            You CANNOT add positive feedback to items that are "too long". I'm afraid there's no specified maximum duration.
            If an item is too long, a ValueError will be thrown.
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
        try:
            response = _api_json(f"/history/{self.historyID}/feedback", headers=self._parentUser.headers, jsonData=payload)
        except (requests.exceptions.RequestException, requests.exceptions.HTTPError) as e:
            try:
                responseJson = e.response.json()
                responseStatus = responseJson["detail"]["status"]
                responseMessage = responseJson["detail"]["message"]
                # If those keys aren't present it'll error out and raise e anyway.
            except:
                raise e
            if responseStatus == "invalid_feedback" and "Positive feedback can be specified only for short audio" in responseMessage:
                logging.error("This audio is too long to add positive feedback text, re-sending feedback without the text.")
                payload["feedback"] = ""
                response = _api_json(f"/history/{self.historyID}/feedback", headers=self._parentUser.headers, jsonData=payload)
            else:
                raise e
        return response

    def delete(self):
        """
        Deletes the item from your history.
        """
        response = _api_del("/history/" + self.historyID, self._parentUser.headers)
        self._historyID = ""



