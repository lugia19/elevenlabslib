from __future__ import annotations

import datetime
import io
import mimetypes
import zipfile

from typing import TYPE_CHECKING, TextIO

from fuzzywuzzy import process

from elevenlabslib.Dub import Dub
from elevenlabslib.Model import Model
from elevenlabslib.Project import Project
from elevenlabslib.PronunciationDictionary import PronunciationDictionary
from elevenlabslib.Voice import ClonedVoice, ProfessionalVoice, LibraryVoiceData
from elevenlabslib.Voice import EditableVoice
from elevenlabslib.Voice import DesignedVoice


if TYPE_CHECKING:
    from elevenlabslib.HistoryItem import HistoryItem
from elevenlabslib.Voice import Voice

from elevenlabslib.helpers import *
from elevenlabslib.helpers import _api_json, _api_get, _api_multipart, _PeekQueue, _api_tts_with_concurrency, _NumpyPlaybacker, _NumpyMp3Streamer


class User:
    """
    Represents a user of the ElevenLabs API, including subscription information.

    This is the class that can be used to query for the user's available voices and create new ones.
    """
    def __init__(self, xi_api_key:str):
        """
        Initializes a new instance of the User class.

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

    def get_models(self) -> list[Model]:
        """
        This function returns all the available models for this account as Model.

        Returns:
            list[Model]: All the available models for this account, as Model instances.
        """
        modelList = list()
        response = _api_get("/models", self._headers)
        modelDataList = response.json()
        for modelData in modelDataList:
            modelList.append(Model(modelData, self))
        return modelList

    def get_model_by_id(self, modelID:str) -> Model:
        response = _api_get("/models", self._headers)
        modelDataList = response.json()
        for modelData in modelDataList:
            if modelData["model_id"] == modelID:
                return Model(modelData, self)
        raise ValueError("This model does not exist or is not available for your account.")

    def get_all_voices(self, show_legacy:bool=True) -> list[Voice | DesignedVoice | ClonedVoice | ProfessionalVoice]:
        """
        Gets a list of all voices registered to this account.

        Caution:
            Some of these may be unusable due to subscription tier changes.
            Use get_available_voices if you only need the currently useable ones.

        Returns:
            list[Voice]: A list containing all the voices.
        """
        response = _api_get("/voices", headers=self._headers, params={"show_legacy":show_legacy})
        allVoices: list[Voice] = list()
        voicesData = response.json()
        from elevenlabslib.Voice import Voice
        for voiceData in voicesData["voices"]:
            allVoices.append(Voice.voiceFactory(voiceData, self))
        return allVoices

    def get_available_voices(self, show_legacy:bool=True) -> list[Voice | DesignedVoice | ClonedVoice | ProfessionalVoice]:
        """
        Gets a list of voices this account can currently use for TTS.

        Returns:
            list[Voice]: A list of currently usable voices.
        """
        response = _api_get("/voices", headers=self._headers, params={"show_legacy":show_legacy})
        voicesData = response.json()
        availableVoices = list()
        canUseClonedVoices = self.get_voice_clone_available()
        from elevenlabslib.Voice import Voice
        for voiceData in voicesData["voices"]:
            if voiceData["category"] == "cloned" and not canUseClonedVoices:
                continue
            availableVoices.append(Voice.voiceFactory(voiceData, linkedUser=self))

        return availableVoices

    def get_voice_by_ID(self, voiceID: str) -> Voice | DesignedVoice | ClonedVoice | ProfessionalVoice:
        """
        Gets a specific voice by ID.

        Args:
            voiceID (str): The ID of the voice to get.

        Returns:
            Voice|DesignedVoice|ClonedVoice|ProfessionalVoice: The requested voice.
        """
        response = _api_get("/voices/" + voiceID, headers=self._headers, params={"with_settings":True, "show_legacy":True})
        voiceData = response.json()
        from elevenlabslib.Voice import Voice
        return Voice.voiceFactory(voiceData, self)

    def get_voices_by_name_v2(self, voiceName: str, score_threshold:int=75) -> list[Voice | EditableVoice | ClonedVoice | ProfessionalVoice]:
        """
        Gets a list of voices with the given name.

        Note:
            This is a list as multiple voices can have the same name.

        Args:
            voiceName (str): The name of the voices to get.
            score_threshold (int, Optional): The % chance of a voice being a match required for it to be included in the returned list. Defaults to 75%.

        Returns:
            list[Voice|DesignedVoice|ClonedVoice]: A list of matching voices.
        """
        response = _api_get("/voices", headers=self._headers, params={"show_legacy": True})
        voicesData = response.json()

        from elevenlabslib.Voice import Voice
        list_of_voices = voicesData["voices"]
        all_matches = process.extract({"name":voiceName}, list_of_voices, limit=None, processor=lambda x: x.get("name"))

        # Filter matches to include only those above the score threshold
        filtered_matches = [match for match in all_matches if match[1] >= score_threshold]
        matching_voices = list()
        for voiceData, score in filtered_matches:
            matching_voices.append(Voice.voiceFactory(voiceData, linkedUser=self))
        return matching_voices

    def get_history_items(self) -> list[HistoryItem]:
        warn("This function is deprecated. Please use get_history_items_paginated() instead, which uses pagination.", DeprecationWarning)
        return self.get_history_items_paginated(maxNumberOfItems=-1)


    def get_history_items_paginated(self, maxNumberOfItems:int=100, startAfterHistoryItem: Union[str, HistoryItem]=None) -> list[HistoryItem]:
        """
        This function returns numberOfItems history items, starting from the newest (or the one specified with startAfterHistoryItem) and returning older ones.

        Args:
            maxNumberOfItems (int): The maximum number of history items to get. A value of 0 or less means all of them.
            startAfterHistoryItem (str|HistoryItem): The history item (or its ID) from which to start returning items.
        Returns:
            list[HistoryItem]: A list containing the requested history items.
        """

        from elevenlabslib.HistoryItem import HistoryItem
        params = {}

        if startAfterHistoryItem is not None:
            if isinstance(startAfterHistoryItem, HistoryItem):
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
                outputList.append(HistoryItem(value, self))
            #We got back at most singleRequestLimit items.
            params["start_after_history_item_id"] = historyData["last_history_item_id"]

            #In case we're done early.
            if not historyData["has_more"]:
                return outputList

        params["page_size"] = maxNumberOfItems
        response = _api_get("/history", headers=self._headers, params=params)

        historyData = response.json()

        for value in historyData["history"]:
            outputList.append(HistoryItem(value, self))
        return outputList


    def get_history_item(self, historyItemID:Union[str, GenerationInfo]) -> HistoryItem:
        """
        Args:
            historyItemID: The HistoryItem ID.

        Returns:
            HistoryItem: The corresponding HistoryItem
        """
        if isinstance(historyItemID, GenerationInfo):
            historyItemID = historyItemID.history_item_id

        response = _api_get(f"/history/{historyItemID}", headers=self._headers)
        historyData = response.json()
        from elevenlabslib.HistoryItem import HistoryItem
        return HistoryItem(historyData, self)

    def download_history_items_v2(self, historyItems:list[str | HistoryItem]) -> dict[HistoryItem, tuple[bytes, str]]:
        """
        Download multiple history items and return a dictionary where the key is the HistoryItem and the value is a tuple consisting of the bytes of the audio and its filename.

        Args:
            historyItems (list[str|HistoryItem]): List of history items (or their IDs) to download.

        Returns:
            dict[HistoryItem, bytes]: Dictionary where the key is the historyItem and the value is a tuple of the bytes of the mp3 file and its filename.
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

    def download_history_items(self, historyItems:list[str | HistoryItem]) -> dict[str, bytes]:
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
        warn("This method is deprecated. Please use generate_voice instead.", DeprecationWarning)

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

    def save_designed_voice(self, temporaryVoiceID: Union[str, tuple[str, bytes]], voiceName:str, voiceDescription:str = "") -> DesignedVoice:
        """
            Saves a voice generated via design_voice to your account, with the given name.

            Args:
                temporaryVoiceID (str|tuple(str,bytes)): The temporary voiceID of the generated voice. It also supports directly passing the tuple from design_voice.
                voiceName (str): The name you would like to give to the new voice.
                voiceDescription (str): The description you would like to give to the new voice.

            Returns:
                DesignedVoice: The newly created voice
        """
        warn("This method is deprecated. Please use save_generated_voice instead.", DeprecationWarning)
        if temporaryVoiceID is tuple:
            temporaryVoiceID = temporaryVoiceID[0]
        payload = {
            "voice_name" : voiceName,
            "generated_voice_id" : temporaryVoiceID,
            "voice_description": voiceDescription
        }
        response = _api_json("/voice-generation/create-voice", headers=self._headers, jsonData=payload)

        return self.get_voice_by_ID(response.json()["voice_id"])

    def generate_voice(self, voice_description: str, text: str = None, auto_generate_text: bool = False,
                       output_format: str = "mp3_44100_192") -> list[tuple[str, bytes, float]]:
        """
        Calls the updated API endpoint that generates voice previews based on the given description.

        Args:
            voice_description (str): Description of the voice to generate. Must be between 20-1000 characters.
            text (str, optional): Text to generate audio for. Must be between 100-1000 characters.
                Required unless auto_generate_text is True.
            auto_generate_text (bool, optional): Whether to automatically generate suitable text.
                Defaults to False.
            output_format (str, optional): Output format for the generated audio.
                Defaults to "mp3_44100_192".

        Returns:
            list[tuple[str, bytes, float]]: A list of tuples, each containing:
                - generated_voice_id (str): Temporary ID for the generated voice
                - audio_bytes (bytes): Audio data for the preview
                - duration_secs (float): Duration of the audio in seconds

        Raises:
            ValueError: If voice_description is not between 20-1000 characters or
                       if text is not between 100-1000 characters when required.
        """
        # Validate input parameters
        if not (20 <= len(voice_description) <= 1000):
            raise ValueError("voice_description must be between 20 and 1000 characters")

        if not auto_generate_text and (text is None or not (100 <= len(text) <= 1000)):
            raise ValueError("text must be between 100 and 1000 characters when auto_generate_text is False")

        payload = {
            "voice_description": voice_description,
            "auto_generate_text": auto_generate_text
        }

        if text is not None:
            payload["text"] = text

        params = {"output_format": output_format} if output_format else {}

        response = _api_json("/text-to-voice/create-previews", headers=self._headers,
                             jsonData=payload, params=params)

        result = response.json()
        previews = []

        for preview in result["previews"]:
            audio_data = base64.b64decode(preview["audio_base_64"])
            previews.append((
                preview["generated_voice_id"],
                audio_data,
                preview.get("duration_secs", 0)
            ))

        return previews

    def save_generated_voice(self, generated_voice_id: str, voice_name: str, voice_description: str,
                             labels: dict[str, str] = None) -> EditableVoice:
        """
        Saves a voice generated via generate_voice to your account.

        Args:
            generated_voice_id (str): The temporary voice ID returned by generate_voice.
            voice_name (str): The name you would like to give to the new voice.
            voice_description (str): The description for the voice. Must be between 20-1000 characters.
            labels (dict[str, str], optional): Metadata to add to the created voice. Defaults to None.

        Returns:
            DesignedVoice: The newly created voice

        Raises:
            ValueError: If voice_description is not between 20-1000 characters.
        """
        if not (20 <= len(voice_description) <= 1000):
            raise ValueError("voice_description must be between 20 and 1000 characters")

        payload = {
            "voice_name": voice_name,
            "voice_description": voice_description,
            "generated_voice_id": generated_voice_id,
        }

        if labels:
            payload["labels"] = labels

        response = _api_json("/text-to-voice/create-voice-from-preview", headers=self._headers, jsonData=payload)
        response_data = response.json()

        return self.get_voice_by_ID(response_data["voice_id"])

    def clone_voice(self, name:str, samples:Union[list[str],dict[str, bytes]], description:str = "", remove_background_noise:bool = False, labels:dict[str, str]=None):
        """
        Create a new ClonedVoice object from the given samples.

        Args:
            name (str): Name of the voice to be created.
            samples (list[str]|dict[str, bytes]): List of file paths OR dictionary of sample file names and bytes for the voice samples.
            description (str, Optional): The description of the voice.
            remove_background_noise (bool, optional): Whether to automatically remove background noise. Defaults to false, can worsen quality if noise is not present.
            labels (dict[str, str], optional): The labels to add to the voice.
        Returns:
            ClonedVoice: The new voice.
        """
        if isinstance(samples, list):
            if not (0 < len(samples) <= 25):
                raise ValueError("Please include between 1 and 25 samples.")
            sampleBytes = {}
            for samplePath in samples:
                if "\\" in samplePath:
                    fileName = samplePath[samplePath.rindex("\\") + 1:]
                else:
                    fileName = samplePath
                sampleBytes[fileName] = open(samplePath, "rb").read()
        else:
            sampleBytes = samples

        if not labels:
            labels = dict()

        payload = {"name": name, "description":description, "remove_background_noise": remove_background_noise, "labels":str(labels)}
        files = list()
        for fileName, fileBytes in sampleBytes.items():
            files.append(("files", (fileName, io.BytesIO(fileBytes))))
        response = _api_multipart("/voices/add", self._headers, data=payload, filesData=files)
        return self.get_voice_by_ID(response.json()["voice_id"])

    def search_voice_library(self, search_term: str=None, use_cases: list[str]=None, descriptives: list[str]=None, sort: Optional[LibSort]=LibSort.TRENDING, advanced_filters: LibVoiceInfo=LibVoiceInfo(), starting_page=0, query_page_size=30) -> List[LibraryVoiceData]:
        """
        Allows you to search the voice library with various filters. For parameters which are lists, all voices that match at least one of them will be returned.

        Args:
            search_term (str, Optional): The search term to use, equivalent to typing it into the site.
            use_cases (list, Optional): A list of use cases.
            descriptives (list, Optional): A list of descriptives (Soft, Calm, etc).
            sort (LibSort, Optional): How to sort the voices.
            advanced_filters (LibVoiceInfo, Optional): Allows you to filter voices based on its characteristics (language, accent, etc)
            query_page_size (int, Optional): How many voices to return. Defaults to 30.
            starting_page (int, Optional): The page to start at.
        """

        requested_items = query_page_size
        query_page_size = min(requested_items, 500)
        current_page = starting_page

        if starting_page != 0 and advanced_filters and advanced_filters.language:
            requested_items = (starting_page + 1) * query_page_size
            current_page = 0

        has_more = True
        all_lib_voices = []

        while has_more and len(all_lib_voices) < requested_items:
            query_params = {
                'search': search_term,
                'use_cases': ','.join(use_cases) if use_cases else None,
                'descriptives': ','.join(descriptives) if descriptives else None,
                'sort': sort.value if sort else None,
                'page_size': query_page_size,
                'page': current_page,
            }

            query_params.update(advanced_filters.to_query_params())
            query_params = {k: v for k, v in query_params.items() if v is not None}

            response = _api_get("/shared-voices", self._headers, params=query_params)
            all_data = response.json()

            # Update has_more based on the API response
            has_more = all_data.get("has_more", False)
            voices_data = all_data.get("voices", [])
            lib_voices = [LibraryVoiceData(voice_data) for voice_data in voices_data]

            # Filter by language if necessary
            if advanced_filters.language:
                lib_voices = [voice for voice in lib_voices if voice.speaker_info.language == advanced_filters.language]

            all_lib_voices.extend(lib_voices)

            # Prepare for the next iteration/page
            current_page += 1

        if starting_page != 0 and advanced_filters.language:
            start_index = starting_page * query_page_size

            if len(all_lib_voices) < start_index:
                # If we have fewer items than the start index, return an empty list
                return []
            else:
                # Calculate the end index based on the smaller of either the requested_items or the length of all_lib_voices
                end_index = min(len(all_lib_voices), requested_items)
                # Trim the list to start from the correct offset and contain only the number of items available up to the end_index
                return all_lib_voices[start_index:end_index]
        else:
            return all_lib_voices[:requested_items]

    def add_shared_voice(self, voice:LibraryVoiceData, newName:str) -> Voice:
        """
        Adds a voice from the library to your account.

        Args:
            voice (LibraryVoiceData): A LibraryVoiceData object, from the voice library endpoint.
            newName (str): Name to give to the voice.

        Returns:
            Voice: The newly created voice.
        """
        return self.add_shared_voice_from_URL(voice.share_link, newName)

    def add_shared_voice_from_URL(self, shareURL:str, newName:str) -> Voice:
        """
        Adds a voice from a share link to the account.

        Args:
            shareURL (str): The sharing URL for the voice.
            newName (str): Name to give to the voice.

        Returns:
            Voice: The newly created voice.
        """
        userIDStartIndex = shareURL.index("/voice-lab/share/") + len("/voice-lab/share/")
        voiceIDStartIndex = shareURL.index("/", userIDStartIndex)
        publicUserID = shareURL[userIDStartIndex:voiceIDStartIndex]
        voiceID = shareURL[voiceIDStartIndex+1:]
        if voiceID[-1] == "/":
            voiceID = voiceID[:len(voiceID)-1]

        return self.add_shared_voice_from_info(publicUserID, voiceID, newName)

    def add_shared_voice_from_info(self, publicUserID:str, voiceID:str, newName:str) -> Voice:
        """
        Adds a voice directly from the voiceID and the public userID.

        Args:
            publicUserID (str): The public userID of the voice's creator.
            voiceID (str): The voiceID of the voice.
            newName (str): Name to give to the voice.

        Returns:
            Voice: The newly created voice.
        """
        payload = {"new_name":newName}
        try:
            response = _api_json(f"/voices/add/{publicUserID}/{voiceID}", self._headers, jsonData=payload)
            newVoiceID = response.json()["voice_id"]
            return self.get_voice_by_ID(newVoiceID)
        except requests.exceptions.RequestException as e:
            if e.response.json()["detail"]["status"] == "voice_already_exists":
                raise ValueError(f"You've already added the voice {voiceID} to your account!")
            raise e


    def get_projects(self) -> List[Project]:
        response = _api_get("/projects", headers=self._headers)
        response_json = response.json()
        projects = list()
        for projectData in response_json["projects"]:
            projects.append(Project(projectData, linked_user=self))

        return projects

    def get_project_by_id(self, project_id:str) -> Project:
        response = _api_get(f"/projects/{project_id}", headers=self._headers)
        response_json = response.json()
        return Project(response_json, self)

    def add_project(self, name: str, default_title_voice: [str, Voice], default_paragraph_voice: [str, Voice],
                    default_model: [str| Model], pronunciation_dictionaries=None,
                    from_url: Optional[str] = None, from_document: Optional[str] = None,
                    quality_preset: str = "standard", title: Optional[str] = None,
                    author: Optional[str] = None, isbn_number: Optional[str] = None,
                    volume_normalization: bool = False) -> Project:
        """
        Creates a new project.

        Parameters:
            name (str): Name of the project.
            default_title_voice (str|Voice): Default voice for titles.
            default_paragraph_voice (str|Voice): Default voice for paragraphs.
            default_model (str): Model for the project.
            pronunciation_dictionaries (list[PronunciationDictionary]): Pronunciation dictionary locators.
            from_url (str, optional): Optional URL to initialize project content.
            from_document (str, optional): The filepath to a file from which to initialize the project.
            quality_preset (str, optional): Quality preset for audio. Must be "standard", "high" or "ultra". Qualities higher than standard increase character cost. Defaults to standard.
            title (str, optional): Project title.
            author (str, optional): Author name.
            isbn_number (str, optional): ISBN number.
            volume_normalization (bool, optional): Whether to enable volume normalization. Defaults to False.
        """

        if isinstance(default_title_voice, Voice):
            default_title_voice = default_title_voice.voiceID

        if isinstance(default_paragraph_voice, Voice):
            default_paragraph_voice = default_paragraph_voice.voiceID

        if isinstance(default_model, Model):
            default_model = default_model.modelID

        if from_url and from_document:
            raise ValueError("Specify only one of from_url or from_document.")

        data = {
            'name': name,
            'default_title_voice_id': default_title_voice,
            'default_paragraph_voice_id': default_paragraph_voice,
            'default_model_id': default_model,
            'quality_preset': quality_preset,
            'title': title,
            'author': author,
            'isbn_number': isbn_number,
            'volume_normalization': volume_normalization,
            'pronunciation_dictionary_locators': [
                    {
                        "pronunciation_dictionary_id":pdict.pronunciation_dictionary_id,
                        "version_id":pdict.version_id
                    } for pdict in pronunciation_dictionaries
            ] if pronunciation_dictionaries else []
        }

        files = None
        if from_url:
            data['from_url'] = from_url
        elif from_document:
            mime_type, _ = mimetypes.guess_type(from_document, strict=False)
            if mime_type is None:
                mime_type = 'application/octet-stream'
            files = {'from_document': (os.path.basename(from_document), open(from_document, 'rb'), mime_type)}

        response = _api_multipart("/projects/add", headers=self.headers, data=data, filesData=files)
        return Project(response.json()["project"], self)

    def create_podcast(self,
                       model_id: str,
                       podcast_type: str,  # "conversation" or "bulletin"
                       host_voice: Union[str, Voice],
                       guest_voice: Optional[Union[str, Voice]] = None,  # Required only for "conversation" mode
                       source_text: Optional[str] = None,
                       source_url: Optional[str] = None,
                       quality_preset: str = "standard",
                       duration_scale: str = "default",
                       language: Optional[str] = None,
                       highlights: Optional[List[str]] = None,
                       callback_url: Optional[str] = None) -> Project:
        """
        Creates a new podcast project with simplified parameters.

        Parameters:
            model_id (str): ID of the model to use.
            podcast_type (str): Either 'conversation' or 'bulletin'.
            host_voice (str|Voice): Voice for the host.
            guest_voice (str|Voice, optional): Voice for the guest (required for 'conversation' mode).
            source_text (str, optional): Text content for the podcast. Either this or source_url must be provided.
            source_url (str, optional): URL to extract content from. Either this or source_text must be provided.
            quality_preset (str, optional): Audio quality. Options: 'standard', 'high', 'highest',
                                          'ultra', 'ultra_lossless'. Defaults to 'standard'.
            duration_scale (str, optional): Duration of the podcast. Options: 'short', 'default', 'long'.
                                           Defaults to 'default'.
            language (str, optional): ISO 639-1 two-letter language code.
            highlights (list[str], optional): Brief summary points (10-70 characters each).
            callback_url (str, optional): URL to call when project is converted.

        Returns:
            Project: The created podcast project.
        """
        # Convert Voice objects to voice IDs
        if isinstance(host_voice, Voice):
            host_voice_id = host_voice.voiceID
        else:
            host_voice_id = host_voice

        if guest_voice is not None:
            if isinstance(guest_voice, Voice):
                guest_voice_id = guest_voice.voiceID
            else:
                guest_voice_id = guest_voice
        else:
            guest_voice_id = None

        # Validate basic parameters
        if podcast_type not in ["conversation", "bulletin"]:
            raise ValueError("podcast_type must be either 'conversation' or 'bulletin'")

        if podcast_type == "conversation" and not guest_voice_id:
            raise ValueError("guest_voice is required for conversation mode")

        if not (source_text or source_url):
            raise ValueError("Either source_text or source_url must be provided")

        if source_text and source_url:
            raise ValueError("Provide either source_text or source_url, not both")

        # Validate quality_preset and duration_scale
        valid_presets = ["standard", "high", "highest", "ultra", "ultra_lossless"]
        if quality_preset not in valid_presets:
            raise ValueError(f"Quality preset must be one of: {', '.join(valid_presets)}")

        valid_scales = ["short", "default", "long"]
        if duration_scale not in valid_scales:
            raise ValueError(f"Duration scale must be one of: {', '.join(valid_scales)}")

        # Construct the nested structures internally
        if podcast_type == "conversation":
            mode = {
                "type": "conversation",
                "conversation": {
                    "host_voice_id": host_voice_id,
                    "guest_voice_id": guest_voice_id
                }
            }
        else:  # bulletin
            mode = {
                "type": "bulletin",
                "bulletin": {
                    "host_voice_id": host_voice_id
                }
            }

        if source_text:
            source = {"type": "text", "text": source_text}
        else:
            source = {"type": "url", "url": source_url}

        # Prepare the data payload
        data = {
            'model_id': model_id,
            'mode': mode,
            'source': source,
            'quality_preset': quality_preset,
            'duration_scale': duration_scale
        }

        # Add optional parameters if provided
        if language:
            data['language'] = language

        if highlights:
            data['highlights'] = highlights

        if callback_url:
            data['callback_url'] = callback_url

        # Make the API request
        response = _api_json("/studio/podcasts", headers=self.headers, jsonData=data)

        # Create and return a Project object from the response
        return Project(response.json()["project"], self)

    def create_transcript(self,
                          audio: Union[str, bytes, BinaryIO],
                          model_id: str = "scribe_v1",
                          language_code: Optional[str] = None,
                          tag_audio_events: bool = True,
                          num_speakers: Optional[int] = None,
                          timestamps_granularity: str = "word",
                          diarize: bool = False) -> dict:
        """
        Transcribes speech from an audio file.

        Parameters:
            audio: Can be one of:
                - str: Path to the audio file
                - bytes: Raw audio data
                - BinaryIO: File-like object containing audio data
            model_id (str): The ID of the model to use for transcription. Currently only 'scribe_v1' is available.
            language_code (str, optional): ISO-639-1 or ISO-639-3 language code for the audio file.
            tag_audio_events (bool, optional): Whether to tag audio events like (laughter), (footsteps), etc. Defaults to True.
            num_speakers (int, optional): Maximum number of speakers (1-32). Defaults to model's maximum.
            timestamps_granularity (str, optional): Granularity of timestamps: 'none', 'word', or 'character'. Defaults to 'word'.
            diarize (bool, optional): Whether to annotate which speaker is talking. Limits audio to 8 minutes. Defaults to False.

        Returns:
            dict: The transcription results.
        """
        if num_speakers and (num_speakers < 1 or num_speakers > 32):
            raise ValueError("num_speakers must be between 1 and 32")

        valid_granularities = ["none", "word", "character"]
        if timestamps_granularity not in valid_granularities:
            raise ValueError(f"timestamps_granularity must be one of: {', '.join(valid_granularities)}")

        data = {
            'model_id': model_id,
            'tag_audio_events': tag_audio_events,
            'timestamps_granularity': timestamps_granularity,
            'diarize': diarize
        }

        if language_code:
            data['language_code'] = language_code
        if num_speakers:
            data['num_speakers'] = num_speakers

        # Handle different audio input types
        files = None
        if isinstance(audio, str):
            # Filepath
            mime_type, _ = mimetypes.guess_type(audio, strict=False)
            if mime_type is None:
                mime_type = 'audio/mpeg'  # Default to audio/mpeg if can't determine
            files = {'file': (os.path.basename(audio), open(audio, 'rb'), mime_type)}
        elif isinstance(audio, bytes):
            files = {'file': ('audio.mp3', audio, 'audio/mpeg')}
        else:
            # Assume BinaryIO
            try:
                # Try to get filename if available
                filename = getattr(audio, 'name', 'audio.mp3')
                if isinstance(filename, int):
                    filename = 'audio.mp3'
                files = {'file': (os.path.basename(filename), audio, 'audio/mpeg')}
            except (AttributeError, TypeError):
                raise ValueError("Unsupported audio input type. Must be filepath string, bytes, or file-like object.")

        response = _api_multipart("/speech-to-text", headers=self.headers, data=data, filesData=files)
        return response.json()

    def add_pronunciation_dictionary(self, name:str, description:str, dict_file:Union[str, TextIO]) -> PronunciationDictionary:
        """
        Adds a pronunciation dictionary.
        Parameters:
            name (str): The name for the dictionary.
            description (str): The description.
            dict_file (str|TextIO): The dictionary file, either as a filepath or a TextIO object.
        Returns:
            A PronunciationDictionary instance.
        """
        payload = {"name": name, "description":description}
        if isinstance(dict_file, str):
            dict_file = open(dict_file, "r")
        files = list()
        files.append(("file", dict_file))
        response = _api_multipart("/pronunciation-dictionaries/add-from-file", headers=self.headers, data=payload, filesData=files)


        return PronunciationDictionary(response.json(), self)

    def get_pronunciation_dictionary(self, dictionary_id:str) -> PronunciationDictionary:
        """
        Args:
            dictionary_id: The pronunciation dictionary ID.

        Returns:
            PronunciationDictionary: The corresponding PronunciationDictionary
        """
        response = _api_get(f"/pronunciation-dictionaries/{dictionary_id}", headers=self.headers)
        return PronunciationDictionary(response.json(), self)

    def get_pronunciation_dictionaries(self, max_number_of_items:int=30, start_after_dict:Union[str, PronunciationDictionary] = None) -> List[PronunciationDictionary]:
        """
            This function returns max_number_of_items pronunciation dictionaries, starting from the newest (or the one specified with start_after_dict) and returning older ones.

            Args:
                max_number_of_items (int): The maximum number of dictionaries to get. A value of 0 or less means all of them.
                start_after_dict (str|PronunciationDictionary): The pronunciation dict (or its ID) from which to start returning dicts.
            Returns:
                list[PronunciationDictionary]: A list containing the requested pronunciation dictionaries.
            """
        params = {"page_size": max_number_of_items}
        if start_after_dict:
            params["cursor"] = start_after_dict if isinstance(start_after_dict, str) else start_after_dict.pronunciation_dictionary_id

        if start_after_dict is not None:
            if isinstance(start_after_dict, PronunciationDictionary):
                start_after_dict = start_after_dict.pronunciation_dictionary_id
            import base64
            #Needs to be the dict id but base64 encoded.
            params["cursor"] = base64.b64encode(bytes(start_after_dict, 'utf-8')).decode('utf-8')
        pdicts = list()
        singleRequestLimit = 100
        downloadAll = max_number_of_items <= 0

        while max_number_of_items > singleRequestLimit or downloadAll:
            max_number_of_items -= singleRequestLimit
            # Let's download limit amount of items and append them to the list
            params["page_size"] = singleRequestLimit
            response = _api_get("/pronunciation-dictionaries", headers=self._headers, params=params)
            pdict_data = response.json()
            for value in pdict_data["pronunciation_dictionaries"]:
                pdicts.append(PronunciationDictionary(value, self))
            # We got back at most singleRequestLimit items.
            params["cursor"] = pdict_data["next_cursor"]

            # In case we're done early.
            if not pdict_data["has_more"]:
                return pdicts

        params["page_size"] = max_number_of_items
        response = _api_get("/pronunciation-dictionaries", headers=self._headers, params=params)

        pdict_data = response.json()

        for value in pdict_data["pronunciation_dictionaries"]:
            pdicts.append(PronunciationDictionary(value, self))

        return pdicts

    def generate_sfx(self, prompt: str, sfx_generation_options: SFXOptions = SFXOptions()) -> \
            tuple[Future[bytes], Future[GenerationInfo]]:
        """
        Generates a sound effect from a text prompt and returns the audio data as bytes.

        Tip:
            If you would like to save the audio to disk or otherwise, you can use helpers.save_audio_bytes().

        Args:
            prompt (str): The text prompt..
            sfx_generation_options (SFXOptions): Options for the SFX generation, such as duration, prompt adherence.
        Returns:
            tuple[Future[bytes], Optional[GenerationInfo]]:
            - A future that will contain the bytes of the audio file once the generation is complete.
            - An optional future that will contain information about the generation.
        """
        payload = {"text": prompt}
        if sfx_generation_options.duration_seconds:
            payload["duration_seconds"] = sfx_generation_options.duration_seconds
        if sfx_generation_options.prompt_influence:
            payload["prompt_influence"] = sfx_generation_options.prompt_influence

        generationID = f"SFX - {prompt} - {time.time()}"
        requestFunction = lambda: _api_json("/sound-generation", self.headers, jsonData=payload)

        audio_future = concurrent.futures.Future()
        info_future = concurrent.futures.Future()

        def wrapped():
            responseConnection = _api_tts_with_concurrency(requestFunction, generationID, self.generation_queue)
            response_headers = responseConnection.headers
            responseData = responseConnection.content
            info_future.set_result(GenerationInfo(character_cost=int(response_headers.get("character-cost", "-1"))))
            audio_future.set_result(responseData)
        threading.Thread(target=wrapped).start()

        return audio_future, info_future

    def isolate_audio(self, audio:Union[bytes, BinaryIO]) -> tuple[Future[bytes], Future[GenerationInfo]]:
        """
        Isolate the voice in the given audio.

        Parameters:
            audio (bytes|BinaryIO): The audio to isolate voice from.
        Returns:
            tuple[Future[bytes], Optional[GenerationInfo]]:
                - A future that will contain the bytes of the audio file once the generation is complete.
                - An optional future that will contain the GenerationInfo object for the generation.
        """
        path = "/audio-isolation/stream"
        source_audio, _ = io_hash_from_audio(audio)
        audio_future, generation_info_future = concurrent.futures.Future(), concurrent.futures.Future()
        files = {"audio": source_audio}
        def wrapper():
            responseConnection = _api_multipart(path, headers=self.headers, data={}, stream=True, filesData=files)
            response_headers = responseConnection.headers
            audio_data = responseConnection.content

            generation_info_future.set_result(GenerationInfo(character_cost=int(response_headers.get("character-cost", "-1"))))

            audio_future.set_result(audio_data)
        threading.Thread(target=wrapper).start()

        return audio_future, generation_info_future

    def isolate_audio_stream(self,
                             audio:Union[bytes, BinaryIO],
                             playback_options: PlaybackOptions = PlaybackOptions(),
                             disable_playback: bool = False
                             ) -> tuple[queue.Queue[numpy.ndarray], Optional[Future[sounddevice.OutputStream]], Future[GenerationInfo]]:
        """
        Isolate the voice in the given audio and stream the result.

        Parameters:
            audio (bytes|BinaryIO): The audio to isolate voice from.
            playback_options (PlaybackOptions, optional): Options for the audio playback such as the device to use and whether to run in the background.
            disable_playback (bool, optional): Allows you to disable playback altogether.
        Returns:
            tuple[queue.Queue[numpy.ndarray], Optional[Future[OutputStream]], Future[GenerationInfo]]:
                - A queue containing the numpy audio data as float32 arrays.
                - An optional future for controlling the playback, returned if playback is not disabled.
                - An future containing a GenerationInfo with metadata.
        """

        response_connection_future = concurrent.futures.Future()
        path = "/audio-isolation/stream"
        source_audio, _ = io_hash_from_audio(audio)
        dummy_gen_options = GenerationOptions(output_format="mp3_44100_192")  # Used to indicate the audio format
        files = {"audio": source_audio}

        def wrapper():
            response_connection_future.set_result(_api_multipart(path, headers=self.headers, data={}, stream=True, filesData=files))

        threading.Thread(target=wrapper).start()
        streamer = _NumpyMp3Streamer(response_connection_future, dummy_gen_options, WebsocketOptions(), audio)

        audio_stream_future = None

        if disable_playback:
            mainThread = threading.Thread(target=streamer.begin_streaming)
            mainThread.start()
        else:
            audio_stream_future = concurrent.futures.Future()
            player = _NumpyPlaybacker(streamer.playback_queue, playback_options, dummy_gen_options)
            threading.Thread(target=streamer.begin_streaming).start()

            if playback_options.runInBackground:
                playback_thread = threading.Thread(target=player.begin_playback, args=(audio_stream_future,))
                playback_thread.start()
            else:
                player.begin_playback(audio_stream_future)

        generation_info_future = concurrent.futures.Future()

        def wrapper():
            connection_headers = streamer.connection_future.result().headers
            generation_info_future.set_result(GenerationInfo(character_cost=int(connection_headers.get("character-cost", "-1"))))
        threading.Thread(target=wrapper).start()

        return streamer.userfacing_queue, audio_stream_future, generation_info_future

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
        generationOptions = dataclasses.replace(generationOptions)
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

    def get_usage_stats(self, start_time:Union[datetime.datetime, int], end_time:Union[datetime.datetime, int]=None,
                        include_workspace_metrics:bool=False, breakdown_type:Optional[str]="voice"):
        """
        Returns the usage stats for the user.
        Parameters:
            start_time (datetime.datetime|int): The start of the usage window in MILLIseconds.
            end_time (datetime.datetime|int, Optional): The end of the usage window in MILLIseconds. Defaults to today's date.
            include_workspace_metrics (bool, Optional): Whether to include workspace metrics. Defaults to false.
            breakdown_type (str, Optional): How to break down the results. Must be one of none, voice, user, api_keys, product_type.

        Returns:
            A tuple containing:
                -The data formatted as a dict with datetime objects as keys
                -The data in its raw format
        """
        if not end_time:
            end_time = datetime.datetime.combine(datetime.datetime.today().date(), datetime.time(23, 59, 59))

        params = {
            "start_unix": int(start_time) if isinstance(start_time, int) or isinstance(end_time, float) else int(start_time.timestamp()*1000),
            "end_unix": int(end_time) if isinstance(end_time, int) or isinstance(end_time, float) else int(end_time.timestamp()*1000),
            "include_workspace_metrics": include_workspace_metrics,
            "breakdown_type": breakdown_type
        }

        raw_data = _api_get("usage/character-stats", headers=self.headers, params=params).json()

        transformed_data = {}
        for i, timestamp in enumerate(raw_data['time']):
            date = datetime.datetime.fromtimestamp(timestamp / 1000)
            if date not in transformed_data:
                transformed_data[date] = {}
            for name, usage_list in raw_data['usage'].items():
                transformed_data[date][name] = usage_list[i]
        return transformed_data, raw_data

    def create_dub(self, name: str, target_lang: str, source_url: str = "", source_file_path: str= None, source_lang: str = "auto", num_speakers: int = 0,
                   watermark: bool = False, start_time: int = None, end_time: int = None, highest_resolution: bool = False,
                   drop_background_audio: bool = False, use_profanity_filter: bool = False) -> Tuple[Dub, int]:
        """
        Dubs a video or an audio file into the given language.

        Args:
            name (str): Name of the dubbing project.
            target_lang (str): The target language to dub the content into.
            source_url (str): URL of the source video/audio file.
            source_file_path (str, optional): File path of the audio/video file to dub. If provided, it will be used instead of source_url.
            source_lang (str, optional): Source language. Defaults to "auto".
            num_speakers (int, optional): Number of speakers to use for the dubbing. Set to 0 to automatically detect the number of speakers. Defaults to 0.
            watermark (bool, optional): Whether to apply a watermark to the output video. Defaults to False.
            start_time (int, optional): Start time of the source video/audio file.
            end_time (int, optional): End time of the source video/audio file.
            highest_resolution (bool, optional): Whether to use the highest resolution available. Defaults to False.
            drop_background_audio (bool, optional): An advanced setting. Whether to drop background audio from the final dub. Defaults to False.
            use_profanity_filter (bool, optional): [BETA] Whether transcripts should have profanities censored with the words '[censored]'. Defaults to False.

        Returns:
            dict: A dictionary containing the dubbing_id and expected_duration_sec of the dubbing task.
        """
        if source_url == "":
            source_url = None
        payload = {
            "name": name,
            "source_url": source_url,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "num_speakers": num_speakers,
            "watermark": watermark,
            "highest_resolution": highest_resolution,
            "drop_background_audio": drop_background_audio,
            "use_profanity_filter": use_profanity_filter
        }
        if start_time is not None:
            payload["start_time"] = start_time
        if end_time is not None:
            payload["end_time"] = end_time

        files = None
        if source_file_path is not None:
            payload.pop("source_url")
            mime_type, _ = mimetypes.guess_type(source_file_path)
            if mime_type is None:
                mime_type = 'application/octet-stream'
            files = {"file": (os.path.basename(source_file_path), open(source_file_path, "rb"), mime_type)}


        if not source_file_path and not source_url:
            raise ValueError("You have to specify either source_file or source_url!")

        response = _api_multipart("/dubbing", headers=self.headers, data=payload, filesData=files)
        response_data = response.json()

        dub_data = {
            "dubbing_id": response_data["dubbing_id"],
            "name": name,
            "status": "in_progress",
            "target_languages": [target_lang]
        }

        return Dub(dub_data, self, response_data["expected_duration_sec"]), response_data["expected_duration_sec"]
    def get_dub_by_id(self, dubbing_id: str) -> Dub:
        """
        Returns metadata about a dubbing project, including whether it's still in progress or not.

        Args:
            dubbing_id (str): ID of the dubbing project.

        Returns:
            dict: A dictionary containing the metadata of the dubbing project.
        """
        response = _api_get(f"/dubbing/{dubbing_id}", headers=self.headers)
        return Dub(response.json(), self)