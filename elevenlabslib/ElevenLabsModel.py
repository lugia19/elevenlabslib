from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elevenlabslib.ElevenLabsUser import ElevenLabsUser

class ElevenLabsModel:
    """
    Represents a TTS/Voice Conversion model, as accessible by a user.
    """
    def __init__(self, modelData, linkedUser: ElevenLabsUser):
        self._linkedUser = linkedUser

        self._name = modelData["name"]
        self._description = modelData["description"]
        self._modelID = modelData["model_id"]

        self._max_characters = modelData["max_characters_request_subscribed_user"]
        self._max_characters_free = modelData["max_characters_request_free_user"]

        self._cost_factor = modelData["token_cost_factor"]
        self._supportsVoiceConversion = modelData["can_do_voice_conversion"]

        self._languages = modelData["languages"]


        self._fullMetaData = modelData

    @property
    def metadata(self):
        """
        The full metadata associated with the sample.
        """
        return self._fullMetaData

    @property
    def name(self):
        """
        The name of the model.
        """
        return self._name

    @property
    def description(self):
        """
        The description of the model.
        """
        return self._description

    @property
    def modelID(self):
        """
        The unique modelID.
        """
        return self._modelID

    @property
    def maxCharacters(self):
        """
        The maximum number of characters the user can send in one request.
        """
        if self._linkedUser.get_subscription_data()["tier"] != "free":
            return self._max_characters
        else:
            return self._max_characters_free

    @property
    def costFactor(self):
        """
        The cost factor (how many characters each character requested subtracts).
        """
        return self._cost_factor

    @property
    def supportsVoiceConversion(self):
        """
        Whether the model supports (or will support) voice conversion
        """
        return self._supportsVoiceConversion

    @property
    def supportedLanguages(self):
        """
        Returns:
            List of dicts, where each dict has a language_id and a name field.
        """

        #This seems redundant, but it's just to account for future changes.
        languageList = list()
        for language in self._languages:
            languageList.append({
                "language_id":language["language_id"],
                "name":language["name"]
            })
        return languageList
