from __future__ import annotations
import io
import queue
import zipfile

from typing import TYPE_CHECKING, BinaryIO, Union, List, Tuple, Any
from warnings import warn

from fuzzywuzzy import process

from elevenlabslib.ElevenLabsModel import ElevenLabsModel
from elevenlabslib.ElevenLabsVoice import ElevenLabsClonedVoice, ElevenLabsProfessionalVoice
from elevenlabslib.ElevenLabsVoice import ElevenLabsEditableVoice
from elevenlabslib.ElevenLabsVoice import ElevenLabsDesignedVoice


if TYPE_CHECKING:
    from elevenlabslib.ElevenLabsHistoryItem import ElevenLabsHistoryItem
    from elevenlabslib.ElevenLabsVoice import ElevenLabsVoice

from elevenlabslib.helpers import *
from elevenlabslib.helpers import _api_json, _api_del, _api_get, _api_multipart, _PeekQueue


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
        self._headers = dict()
        for key, value in default_headers.items():
            self._headers[key] = value
        self._headers["xi-api-key"] = self.xi_api_key
        self.generation_queue = _PeekQueue()
        self._subscriptionTier = None           #Used to cache the result for mp3/pcm_highest
        try:
            self.update_audio_quality()
        except (requests.exceptions.RequestException, requests.exceptions.HTTPError) as e:
            try:
                responseJson = e.response.json()
                responseStatus = responseJson["detail"]["status"]
                # If those keys aren't present it'll error out and raise e anyway.
            except:
                raise e

            if responseStatus == "invalid_api_key":
                raise ValueError("Invalid API Key!")
            else:
                raise e

    @property
    def headers(self) -> dict:
        """
        Returns:
            dict: The headers used for API requests.
        """
        return self._headers

    @property
    def xi_api_key(self) -> str:
        return self._xi_api_key


    #Userdata-centric functions
    def get_user_data(self) -> dict:
        """
        Returns:
             dict: All the information returned by the /v1/user endpoint.
        """
        response = _api_get("/user/", self._headers)
        userData = response.json()
        return userData

    def get_subscription_data(self) -> dict:
        """
        Returns:
             dict: All the information returned by the /v1/user/subscription endpoint.
        """
        response = _api_get("/user/subscription", self._headers)
        subscriptionData = response.json()
        return subscriptionData

    def get_character_info(self) -> (int, int, bool):
        """
        Returns:
            (int, int, bool): A tuple containing the number of characters used up, the maximum, and if the maximum can be increased.
        """
        subData = self.get_subscription_data()
        return subData["character_count"], subData["character_limit"], (subData["can_extend_character_limit"] and subData["allowed_to_extend_character_limit"])

    def get_current_character_count(self) -> int:
        warn("Deprecated in favor of user.get_character_info().", DeprecationWarning)
        subData = self.get_subscription_data()
        return subData["character_count"]

    def get_character_limit(self) -> int:
        warn("Deprecated in favor of user.get_character_info().", DeprecationWarning)
        subData = self.get_subscription_data()
        return subData["character_limit"]

    def get_can_extend_character_limit(self) -> bool:
        warn("Deprecated in favor of user.get_character_info().", DeprecationWarning)
        subData = self.get_subscription_data()
        return subData["can_extend_character_limit"] and subData["allowed_to_extend_character_limit"]

    def get_voice_clone_available(self) -> bool:
        """
        Returns:
            bool: True if the user can use instant voice cloning, False otherwise.
        """
        subData = self.get_subscription_data()
        return subData["can_use_instant_voice_cloning"]

    def get_next_invoice(self) -> dict | None:
        """
        Returns:
            dict | None: The next invoice's data, or None if there is no next invoice.
        """
        subData = self.get_subscription_data()
        return subData["next_invoice"]

    #Other endpoints
    def get_available_models(self) -> list[dict]:
        warn("This function is deprecated. Use get_models instead.", DeprecationWarning)
        response = _api_get("/models", self._headers)
        userData = response.json()
        return userData

    def get_models(self) -> list[ElevenLabsModel]:
        """
        This function returns all the available models for this account as ElevenLabsModel.

        Returns:
            list[ElevenLabsModel]: All the available models for this account, as ElevenLabsModel instances.
        """
        modelList = list()
        response = _api_get("/models", self._headers)
        modelDataList = response.json()
        for modelData in modelDataList:
            modelList.append(ElevenLabsModel(modelData, self))
        return modelList

    def get_model_by_id(self, modelID:str) -> ElevenLabsModel:
        response = _api_get("/models", self._headers)
        modelDataList = response.json()
        for modelData in modelDataList:
            if modelData["model_id"] == modelID:
                return ElevenLabsModel(modelData, self)
        raise ValueError("This model does not exist or is not available for your account.")

    def get_all_voices(self) -> list[ElevenLabsVoice | ElevenLabsDesignedVoice | ElevenLabsClonedVoice | ElevenLabsProfessionalVoice]:
        """
        Gets a list of all voices registered to this account.

        Caution:
            Some of these may be unusable due to subscription tier changes.
            Use get_available_voices if you only need the currently useable ones.

        Returns:
            list[ElevenLabsVoice]: A list containing all the voices.
        """
        response = _api_get("/voices", headers=self._headers)
        allVoices: list[ElevenLabsVoice] = list()
        voicesData = response.json()
        from elevenlabslib.ElevenLabsVoice import ElevenLabsVoice
        for voiceData in voicesData["voices"]:
            allVoices.append(ElevenLabsVoice.voiceFactory(voiceData, self))
        return allVoices

    def get_available_voices(self) -> list[ElevenLabsVoice | ElevenLabsDesignedVoice | ElevenLabsClonedVoice | ElevenLabsProfessionalVoice]:
        """
        Gets a list of voices this account can currently use for TTS.

        Returns:
            list[ElevenLabsVoice]: A list of currently usable voices.
        """
        response = _api_get("/voices", headers=self._headers)
        voicesData = response.json()
        availableVoices = list()
        canUseClonedVoices = self.get_voice_clone_available()
        from elevenlabslib.ElevenLabsVoice import ElevenLabsVoice
        for voiceData in voicesData["voices"]:
            if voiceData["category"] == "cloned" and not canUseClonedVoices:
                continue
            if voiceData["category"] == "professional" and voiceData["fine_tuning"]["finetuning_state"] != "fine_tuned":
                continue
            availableVoices.append(ElevenLabsVoice.voiceFactory(voiceData, linkedUser=self))

        return availableVoices

    def get_voice_by_ID(self, voiceID: str) -> ElevenLabsVoice | ElevenLabsDesignedVoice | ElevenLabsClonedVoice | ElevenLabsProfessionalVoice:
        """
        Gets a specific voice by ID.

        Args:
            voiceID (str): The ID of the voice to get.

        Returns:
            ElevenLabsVoice|ElevenLabsDesignedVoice|ElevenLabsClonedVoice|ElevenLabsProfessionalVoice: The requested voice.
        """
        response = _api_get("/voices/" + voiceID, headers=self._headers, params={"with_settings":True})
        voiceData = response.json()
        from elevenlabslib.ElevenLabsVoice import ElevenLabsVoice
        return ElevenLabsVoice.voiceFactory(voiceData, self)

    def get_voices_by_name(self, voiceName: str) -> list[ElevenLabsVoice | ElevenLabsDesignedVoice | ElevenLabsClonedVoice | ElevenLabsProfessionalVoice]:
        warn("This function is deprecated. Please use get_voices_by_name_v2() instead, which uses fuzzy matching.", DeprecationWarning)
        matches = self.get_voices_by_name_v2(voiceName, score_threshold=100)
        return matches

    def get_voices_by_name_v2(self, voiceName: str, score_threshold:int=75) -> list[ElevenLabsVoice | ElevenLabsEditableVoice | ElevenLabsClonedVoice | ElevenLabsProfessionalVoice]:
        """
        Gets a list of voices with the given name.

        Note:
            This is a list as multiple voices can have the same name.

        Args:
            voiceName (str): The name of the voices to get.
            score_threshold (int, Optional): The % chance of a voice being a match required for it to be included in the returned list. Defaults to 75%.

        Returns:
            list[ElevenLabsVoice|ElevenLabsDesignedVoice|ElevenLabsClonedVoice]: A list of matching voices.
        """
        response = _api_get("/voices", headers=self._headers)
        voicesData = response.json()

        from elevenlabslib.ElevenLabsVoice import ElevenLabsVoice
        list_of_voices = voicesData["voices"]
        all_matches = process.extract({"name":voiceName}, list_of_voices, limit=None, processor=lambda x: x.get("name"))

        # Filter matches to include only those above the score threshold
        filtered_matches = [match for match in all_matches if match[1] >= score_threshold]
        matching_voices = list()
        for voiceData, score in filtered_matches:
            print(voiceData["name"])
            print(score)
            matching_voices.append(ElevenLabsVoice.voiceFactory(voiceData, linkedUser=self))
        return matching_voices

    def get_history_items(self) -> list[ElevenLabsHistoryItem]:
        warn("This function is deprecated. Please use get_history_items_paginated() instead, which uses pagination.", DeprecationWarning)
        return self.get_history_items_paginated(maxNumberOfItems=-1)


    def get_history_items_paginated(self, maxNumberOfItems:int=100, startAfterHistoryItem:str|ElevenLabsHistoryItem=None) -> list[ElevenLabsHistoryItem]:
        """
        This function returns numberOfItems history items, starting from the newest (or the one specified with startAfterHistoryItem) and returning older ones.

        Args:
            maxNumberOfItems (int): The maximum number of history items to get. A value of 0 or less means all of them.
            startAfterHistoryItem (str|ElevenLabsHistoryItem): The history item (or its ID) from which to start returning items.
        Returns:
            list[ElevenLabsHistoryItem]: A list containing the requested history items.
        """

        from elevenlabslib.ElevenLabsHistoryItem import ElevenLabsHistoryItem
        params = {}

        if startAfterHistoryItem is not None:
            if isinstance(startAfterHistoryItem, ElevenLabsHistoryItem):
                startAfterHistoryItem = startAfterHistoryItem.historyID
            params["start_after_history_item_id"] = startAfterHistoryItem

        outputList = list()
        singleRequestLimit = 1000

        downloadAll = maxNumberOfItems <= 0

        #While it's over the limit OR the user wants to download all items.
        while maxNumberOfItems > singleRequestLimit or downloadAll:
            maxNumberOfItems -= singleRequestLimit
            #Let's download limit amount of items and append them to the list
            params["page_size"] = singleRequestLimit
            response = _api_get("/history", headers=self._headers, params=params)
            historyData = response.json()
            for value in historyData["history"]:
                outputList.append(ElevenLabsHistoryItem(value, self))
            #We got back at most singleRequestLimit items.
            params["start_after_history_item_id"] = historyData["last_history_item_id"]

            #In case we're done early.
            if not historyData["has_more"]:
                return outputList

        params["page_size"] = maxNumberOfItems
        response = _api_get("/history", headers=self._headers, params=params)

        historyData = response.json()

        for value in historyData["history"]:
            outputList.append(ElevenLabsHistoryItem(value, self))
        return outputList


    def get_history_item(self, historyItemID) -> ElevenLabsHistoryItem:
        """
        Args:
            historyItemID: The HistoryItem ID.

        Returns:
            ElevenLabsHistoryItem: The corresponding ElevenLabsHistoryItem
        """
        response = _api_get(f"/history/{historyItemID}", headers=self._headers)
        historyData = response.json()
        from elevenlabslib.ElevenLabsHistoryItem import ElevenLabsHistoryItem
        return ElevenLabsHistoryItem(historyData, self)

    def download_history_items_v2(self, historyItems:list[str|ElevenLabsHistoryItem]) -> dict[ElevenLabsHistoryItem, tuple[bytes, str]]:
        """
        Download multiple history items and return a dictionary where the key is the ElevenLabsHistoryItem and the value is a tuple consisting of the bytes of the audio and its filename.

        Args:
            historyItems (list[str|ElevenLabsHistoryItem]): List of history items (or their IDs) to download.

        Returns:
            dict[ElevenLabsHistoryItem, bytes]: Dictionary where the key is the historyItem and the value is a tuple of the bytes of the mp3 file and its filename.
        """

        historyItemIDs = list()
        for index, item in enumerate(historyItems):
            if isinstance(item, str):
                historyItemIDs.append(item)
                historyItems[index] = self.get_history_item(item)
            else:
                historyItemIDs.append(item.historyID)

        if len(historyItemIDs) == 1:
            historyItemIDs.append(historyItemIDs[0])

        payload = {"history_item_ids": historyItemIDs}
        response = _api_json("/history/download", headers=self._headers, jsonData=payload)
        historyItemsByFilename = dict()
        for item in historyItems:
            historyItemsByFilename[item.filename] = item



        if len(historyItemIDs) == 1:
            downloadedHistoryItems = {historyItemIDs[0]: response.content}
        else:
            downloadedHistoryItems = {}
            downloadedZip = zipfile.ZipFile(io.BytesIO(response.content))
            # Extract all files and add them to the dict.
            for filePath in downloadedZip.namelist():
                fileName = filePath[filePath.index("/")+1:]
                audioData = downloadedZip.read(filePath)
                assert fileName in historyItemsByFilename.keys()
                originalHistoryItem = historyItemsByFilename[fileName]
                if not originalHistoryItem in downloadedHistoryItems:   #Avoid re-reading duplicates from the zip file.
                    downloadedHistoryItems[originalHistoryItem] = (audioData, fileName)

        return downloadedHistoryItems

    def download_history_items(self, historyItems:list[str|ElevenLabsHistoryItem]) -> dict[str, bytes]:
        warn("This function is deprecated, please use download_history_items_v2 instead.", DeprecationWarning)
        historyItemIDs = list()
        for item in historyItems:
            if isinstance(item, str):
                historyItemIDs.append(item)
            else:
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
                historyID = fileName[fileName.rindex("_") + 1:fileName.rindex(".")]
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

    def save_designed_voice(self, temporaryVoiceID: Union[str, tuple[str, bytes]], voiceName:str, voiceDescription:str = "") -> ElevenLabsDesignedVoice:
        """
            Saves a voice generated via design_voice to your account, with the given name.

            Args:
                temporaryVoiceID (str|tuple(str,bytes)): The temporary voiceID of the generated voice. It also supports directly passing the tuple from design_voice.
                voiceName (str): The name you would like to give to the new voice.
                voiceDescription (str): The description you would like to give to the new voice.

            Returns:
                ElevenLabsDesignedVoice: The newly created voice
        """
        if temporaryVoiceID is tuple:
            temporaryVoiceID = temporaryVoiceID[0]
        payload = {
            "voice_name" : voiceName,
            "generated_voice_id" : temporaryVoiceID,
            "voice_description": voiceDescription
        }
        response = _api_json("/voice-generation/create-voice", headers=self._headers, jsonData=payload)

        return self.get_voice_by_ID(response.json()["voice_id"])


    def clone_voice_by_path(self, name:str, samples: list[str]|str) -> ElevenLabsClonedVoice:
        """
            Create a new ElevenLabsClonedVoice object by providing the voice name and a list of sample file paths.

            Args:
                name (str): Name of the voice to be created.
                samples (list[str]|str): List of file paths for the voice samples (or a single path).

            Returns:
                ElevenLabsClonedVoice: The new voice.
        """
        if isinstance(samples, str):
            samples = list(samples)

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

    def add_shared_voice_from_URL(self, shareURL:str, newName:str) -> ElevenLabsDesignedVoice:
        """
        Adds a voice from a share link to the account.

        Args:
            shareURL (str): The sharing URL for the voice.
            newName (str): Name to give to the voice.

        Returns:
            ElevenLabsDesignedVoice: The newly created voice.
        """
        userIDStartIndex = shareURL.index("/voice-lab/share/") + len("/voice-lab/share/")
        voiceIDStartIndex = shareURL.index("/", userIDStartIndex)
        publicUserID = shareURL[userIDStartIndex:voiceIDStartIndex]
        voiceID = shareURL[voiceIDStartIndex+1:]
        if voiceID[-1] == "/":
            voiceID = voiceID[:len(voiceID)-1]

        return self.add_shared_voice_from_info(publicUserID, voiceID, newName)

    def add_shared_voice_from_info(self, publicUserID:str, voiceID:str, newName:str) -> ElevenLabsDesignedVoice:
        """
        Adds a voice directly from the voiceID and the public userID.

        Args:
            publicUserID (str): The public userID of the voice's creator.
            voiceID (str): The voiceID of the voice.
            newName (str): Name to give to the voice.

        Returns:
            ElevenLabsDesignedVoice: The newly created voice.
        """
        payload = {"new_name":newName}
        try:
            response = _api_json(f"/voices/add/{publicUserID}/{voiceID}", self._headers, jsonData=payload)
            newVoiceID = response.json()["voice_id"]
            return self.get_voice_by_ID(newVoiceID)
        except requests.exceptions.RequestException as e:
            if e.response.json()["detail"]["status"] == "voice_already_cloned":
                raise ValueError(f"You've already added the voice {voiceID} to your account!")
            raise e

    def update_audio_quality(self):
        self._subscriptionTier = self.get_subscription_data()["tier"]

    def get_real_audio_format(self, generationOptions:GenerationOptions) -> GenerationOptions:
        """
        Parameters:
            generationOptions (GenerationOptions): A GenerationOptions object.

        Returns:
            A GenerationOptions object with a real audio format (if the original was mp3_highest or pcm_highest, it's modified accordingly, otherwise returned directly)
        """
        if self._subscriptionTier is None:
            self.update_audio_quality()

        if "highest" in generationOptions.output_format:
            if "mp3" in generationOptions.output_format:
                if subscription_tiers.index(self._subscriptionTier) >= subscription_tiers.index("creator"):
                    generationOptions.output_format = "mp3_44100_192"
                else:
                    generationOptions.output_format = "mp3_44100_128"
            else:
                if subscription_tiers.index(self._subscriptionTier) >= subscription_tiers.index("pro"):
                    generationOptions.output_format = "pcm_44100"
                else:
                    generationOptions.output_format = "pcm_24000"

        return generationOptions