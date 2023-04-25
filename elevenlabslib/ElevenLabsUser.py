from __future__ import annotations
import io
import zipfile

from typing import TYPE_CHECKING, BinaryIO, Union

from elevenlabslib.ElevenLabsVoice import ElevenLabsClonedVoice
from elevenlabslib.ElevenLabsVoice import ElevenLabsDesignedVoice


if TYPE_CHECKING:
    from elevenlabslib.ElevenLabsHistoryItem import ElevenLabsHistoryItem
    from elevenlabslib.ElevenLabsVoice import ElevenLabsVoice

from elevenlabslib.helpers import *
from elevenlabslib.helpers import _api_json,_api_del,_api_get,_api_multipart


class ElevenLabsUser:
    """
    Represents a user of the ElevenLabs API, including subscription information.

    This is the class that can be used to query for the user's available voices and create new ones.
    """
    def __init__(self, xi_api_key:str):
        """
        Initializes a new instance of the ElevenLabsUser class.

        Args:
            xi_api_key (str): The user's API key.

        Raises:
            ValueError: If the API Key is invalid.
        """
        self._xi_api_key = xi_api_key
        self._headers = default_headers
        self._headers["xi-api-key"] = self._xi_api_key
        try:
            self.get_available_voices()
        except requests.exceptions.RequestException:
            raise ValueError("Invalid API Key!")

    def _get_subscription_data(self) -> dict:
        response = _api_get("/user/subscription", self._headers)
        subscriptionData = response.json()
        return subscriptionData

    @property
    def headers(self) -> dict:
        """
        Returns:
            dict: The headers used for API requests.
        """
        return self._headers

    def get_user_data(self) -> dict:
        """
        Returns:
             dict: All the information returned by the /v1/user endpoint.
        """
        response = _api_get("/user/subscription", self._headers)
        userData = response.json()
        return userData
    def get_current_character_count(self) -> int:
        """
        Returns:
            int: The number of characters used up.
        """
        subData = self._get_subscription_data()
        return subData["character_count"]

    def get_character_limit(self) -> int:
        """
        Returns:
            int: The user's current character limit.
        """
        subData = self._get_subscription_data()
        return subData["character_limit"]

    def get_can_extend_character_limit(self) -> bool:
        """
        Returns:
            bool: True if the user can (and has enabled) extend their character limit, False otherwise.
        """
        subData = self._get_subscription_data()
        return subData["can_extend_character_limit"] and subData["allowed_to_extend_character_limit"]

    def get_voice_clone_available(self) -> bool:
        """
        Returns:
            bool: True if the user can use instant voice cloning, False otherwise.
        """
        subData = self._get_subscription_data()
        return subData["can_use_instant_voice_cloning"]

    def get_next_invoice(self) -> dict | None:
        """
        Returns:
            dict | None: The next invoice's data, or None if there is no next invoice.
        """
        subData = self._get_subscription_data()
        return subData["next_invoice"]

    def get_all_voices(self) -> list[ElevenLabsVoice | ElevenLabsDesignedVoice | ElevenLabsClonedVoice]:
        """
        Gets a list of all voices registered to this account.

        Caution:
            Some of these may be unusable due to subscription tier changes.
            Use get_available_voices if you only need the currently useable ones.

        Returns:
            list[ElevenLabsVoice]: A list containing all the voices.
        """
        response = _api_get("/voices", headers=self._headers)
        availableVoices: list[ElevenLabsVoice] = list()
        voicesData = response.json()
        from elevenlabslib.ElevenLabsVoice import ElevenLabsVoice
        for voiceData in voicesData["voices"]:
            availableVoices.append(ElevenLabsVoice.voiceFactory(voiceData, self))
        return availableVoices

    def get_available_voices(self) -> list[ElevenLabsVoice | ElevenLabsDesignedVoice | ElevenLabsClonedVoice]:
        """
        Gets a list of voices this account can currently use.

        Returns:
            list[ElevenLabsVoice]: A list of currently usable voices.
        """
        allVoices = self.get_all_voices()
        availableVoices = list()
        canUseClonedVoices = self.get_voice_clone_available()
        for voice in allVoices:
            if voice.category == "cloned" and not canUseClonedVoices:
                continue
            availableVoices.append(voice)
        return availableVoices

    def get_voice_by_ID(self, voiceID: str) -> ElevenLabsVoice | ElevenLabsDesignedVoice | ElevenLabsClonedVoice:
        """
        Gets a specific voice by ID.

        Args:
            voiceID (str): The ID of the voice to get.

        Returns:
            ElevenLabsVoice|ElevenLabsDesignedVoice|ElevenLabsClonedVoice: The requested voice.
        """
        response = _api_get("/voices/" + voiceID, headers=self._headers)
        voiceData = response.json()
        from elevenlabslib.ElevenLabsVoice import ElevenLabsVoice
        return ElevenLabsVoice.voiceFactory(voiceData, self)
    def get_voices_by_name(self, voiceName: str) -> list[ElevenLabsVoice | ElevenLabsDesignedVoice | ElevenLabsClonedVoice]:
        """
        Gets a list of voices with the given name.

        Note:
            This is a list as multiple voices can have the same name.

        Args:
            voiceName (str): The name of the voices to get.

        Returns:
            list[ElevenLabsVoice|ElevenLabsDesignedVoice|ElevenLabsClonedVoice]: A list of matching voices.
        """
        allVoices = self.get_available_voices()
        matchingVoices = list()
        for voice in allVoices:
            if voice.initialName == voiceName:
                matchingVoices.append(voice)
        return matchingVoices

    def get_history_items(self) -> list[ElevenLabsHistoryItem]:
        """
        Returns:
            list[ElevenLabsHistoryItem]: A list containing all of the user's history items.
        """
        outputList = list()
        response = _api_get("/history", headers=self._headers)
        historyData = response.json()
        from elevenlabslib.ElevenLabsHistoryItem import ElevenLabsHistoryItem
        for value in historyData["history"]:
            outputList.append(ElevenLabsHistoryItem(value, self))
        return outputList
    def download_history_items(self, historyItems:list[str|ElevenLabsHistoryItem]) -> dict[str, bytes]:
        """
            Download multiple history items and return a dictionary where the key is the history ID
            and the value is the bytes of the mp3 file.

            Args:
                historyItems (list[str|ElevenLabsHistoryItem]): List of history items (or their IDs) to download.

            Returns:
                dict[str, bytes]: Dictionary where the key is the history ID and the value is the bytes of the mp3 file.
            """

        historyItemIDs = list()
        for item in historyItems:
            if item is str:
                historyItemIDs.append(item)
            elif item is ElevenLabsHistoryItem:
                historyItemIDs.append(item.historyID)

        payload = {"history_item_ids": historyItemIDs}
        response = _api_json("/history/download", headers=self._headers, jsonData=payload)

        if len(historyItemIDs) == 1:
            downloadedHistoryItems = {historyItemIDs[0]: response.content}
        else:
            downloadedHistoryItems = {}
            downloadedZip = zipfile.ZipFile(io.BytesIO(response.content))
            #Extract all files and add them to the dict.
            for fileName in downloadedZip.namelist():
                historyID = fileName[:fileName.rindex(".")]
                if "/" in historyID:
                    historyID = historyID[historyID.find("/") + 1:]
                downloadedHistoryItems[historyID] = downloadedZip.read(fileName)

        return downloadedHistoryItems

    def design_voice(self, gender:str, accent:str, age:str, accent_strength:float, sampleText:str = "First we thought the PC was a calculator. Then we found out how to turn numbers into letters and we thought it was a typewriter.")\
            -> (str,bytes):
        """
            Calls the API endpoint that randomly generates a voice based on the given parameters.

            Caution:
                To actually save the generated voice to your account, you must then call save_designed_voice with the temporary voiceID.

            Args:
                gender (str): The gender.
                accent (str): The accent.
                age (str): The age.
                accent_strength (float): How strong the accent should be, between 0.3 and 2.
                sampleText (str): The text that will be used to randomly generate the new voice. Must be at least 100 characters long.
            Returns:
                (str, bytes): A tuple containing the new, temporary voiceID and the bytes of the generated audio.
        """
        if not (0.3 <= accent_strength <= 2):
            raise ValueError("accent_strength must be within 0.3 and 2!")

        payload = {
            "text": sampleText,
            "gender": gender,
            "accent": accent,
            "age": age,
            "accent_strength": accent_strength
        }
        response = _api_json("/voice-generation/generate-voice", headers=self._headers, jsonData=payload)

        return response.headers["generated_voice_id"], response.content

    def save_designed_voice(self, temporaryVoiceID: Union[str, tuple:str, bytes], voiceName:str) -> ElevenLabsDesignedVoice:
        """
            Saves a voice generated via design_voice to your account, with the given name.

            Args:
                temporaryVoiceID (str|tuple(str,bytes)): The temporary voiceID of the generated voice. It also supports directly passing the tuple from design_voice.
                voiceName (str): The name you would like to give to the new voice.

            Returns:
                ElevenLabsDesignedVoice: The newly created voice
        """
        if temporaryVoiceID is tuple:
            temporaryVoiceID = temporaryVoiceID[0]
        payload = {
            "voice_name" : voiceName,
            "generated_voice_id" : temporaryVoiceID
        }
        response = _api_json("/voice-generation/create-voice", headers=self._headers, jsonData=payload)

        return self.get_voice_by_ID(response.json()["voice_id"])


    def clone_voice_by_path(self, name:str, samples: list[str]) -> ElevenLabsClonedVoice:
        """
            Create a new ElevenLabsClonedVoice object by providing the voice name and a list of sample file paths.

            Args:
                name (str): Name of the voice to be created.
                samples (list[str]): List of file paths for the voice samples.

            Returns:
                ElevenLabsClonedVoice: The new voice.
        """
        sampleBytes = {}
        for samplePath in samples:
            if "\\" in samplePath:
                fileName = samplePath[samplePath.rindex("\\") + 1:]
            else:
                fileName = samplePath
            sampleBytes[fileName] = open(samplePath, "rb").read()
        return self.clone_voice_bytes(name, sampleBytes)

    def clone_voice_bytes(self, name:str, samples: dict[str, bytes]) -> ElevenLabsClonedVoice:
        """
            Create a new ElevenLabsGeneratedVoice object by providing the voice name and a dictionary of sample file names and bytes.

            Args:
                name (str): Name of the voice to be created.
                samples (dict[str, bytes]): Dictionary of sample file names and bytes for the voice samples.

            Returns:
                ElevenLabsClonedVoice: The new voice.
            """
        if len(samples.keys()) == 0:
            raise Exception("Please add at least one sample!")
        if len(samples.keys()) > 25:
            raise Exception("Please only add a maximum of 25 samples.")

        payload = {"name": name}
        files = list()
        for fileName, fileBytes in samples.items():
            files.append(("files", (fileName, io.BytesIO(fileBytes))))
        response = _api_multipart("/voices/add", self._headers, data=payload, filesData=files)
        return self.get_voice_by_ID(response.json()["voice_id"])