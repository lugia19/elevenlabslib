from __future__ import annotations
import io
import zipfile

from typing import TYPE_CHECKING, BinaryIO

if TYPE_CHECKING:
    from elevenlabslib.ElevenLabsHistoryItem import ElevenLabsHistoryItem
    from elevenlabslib.ElevenLabsVoice import ElevenLabsVoice
from elevenlabslib.helpers import *


class ElevenLabsUser:
    def __init__(self, xi_api_key:str):
        self._xi_api_key = xi_api_key
        self._headers = default_headers
        self._headers["xi-api-key"] = self._xi_api_key

    def _get_subscription_data(self) -> dict:
        response = api_get("/user/subscription",self._headers)
        if response.ok:
            subscriptionData = response.json()
            return subscriptionData
        else:
            raise Exception(str(response.status_code))

    @property
    def headers(self):
        return self._headers

    #These are all the functions that fetch user info from the API
    def get_current_character_count(self) -> int:
        subData = self._get_subscription_data()
        return subData["character_count"]

    def get_character_limit(self) -> int:
        subData = self._get_subscription_data()
        return subData["character_limit"]

    def get_can_extend_character_limit(self) -> bool:
        subData = self._get_subscription_data()
        return subData["can_extend_character_limit"] and subData["allowed_to_extend_character_limit"]

    def get_voice_clone_available(self) -> bool:
        subData = self._get_subscription_data()
        return subData["can_use_instant_voice_cloning"]

    def get_next_invoice(self) -> dict | None:
        subData = self._get_subscription_data()
        return subData["next_invoice"]



    def get_available_voices(self) -> list[ElevenLabsVoice]:
        response = api_get("/voices", headers=self._headers)
        availableVoices:list[ElevenLabsVoice] = list()
        if response.ok:
            voicesData = response.json()
            from elevenlabslib.ElevenLabsVoice import ElevenLabsVoice
            for voiceData in voicesData["voices"]:
                availableVoices.append(ElevenLabsVoice(voiceData, self))
        else:
            raise Exception(str(response.status_code))
        return availableVoices

    def get_voice_by_ID(self, voiceID:str) -> ElevenLabsVoice:
        response = api_get( "/voices/"+voiceID, headers=self._headers)
        voiceData = response.json()
        from elevenlabslib.ElevenLabsVoice import ElevenLabsVoice
        return ElevenLabsVoice(voiceData, self)

    def get_voices_by_name(self, voiceName:str) -> list[ElevenLabsVoice]:
        allVoices = self.get_available_voices()
        matchingVoices = list()
        for voice in allVoices:
            if voice.initialName == voiceName:
                matchingVoices.append(voice)
        return matchingVoices

    def get_history_items(self) -> list[ElevenLabsHistoryItem]:
        outputList = list()
        response = api_get("/history", headers=self._headers)
        historyData = response.json()
        from elevenlabslib.ElevenLabsHistoryItem import ElevenLabsHistoryItem
        for value in historyData["history"]:
            outputList.append(ElevenLabsHistoryItem(value, self))
        return outputList

    #Returns a dictionary where the key is the historyItem and the value is the bytes of the mp3 file.
    def download_multiple_history_items(self, historyItems: list[ElevenLabsHistoryItem]) -> dict[ElevenLabsHistoryItem, bytes]:
        historyItemsByID = dict()
        for item in historyItems:
            historyItemsByID[item.historyID] = item

        payload = {"history_item_ids": list(historyItemsByID.keys())}
        response = api_json("/history/download", headers=self._headers, jsonData=payload)

        if len(historyItems) == 1:
            downloadedHistoryItems = {historyItems[0]: response.content}
        else:
            downloadedHistoryItems = {}
            downloadedZip = zipfile.ZipFile(io.BytesIO(response.content))
            # Extract all files and add them to the dict.
            for fileName in downloadedZip.namelist():
                historyID = fileName[:fileName.rindex(".")]
                if "/" in historyID:
                    historyID = historyID[historyID.find("/")+1:]
                historyItem = historyItemsByID[historyID]
                downloadedHistoryItems[historyItem] = downloadedZip.read(fileName)
        return downloadedHistoryItems

    # Returns a dictionary where the key is the historyID and the value is the bytes of the mp3 file.
    def download_multiple_history_items_by_ID(self, historyItemIDs:list[str]) -> dict[str, bytes]:
        payload = {"history_item_ids": historyItemIDs}
        response = api_json("/history/download", headers=self._headers, jsonData=payload)

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

    def create_voice_by_path(self, name:str, samples: list[str]) -> ElevenLabsVoice:
        sampleBytes = {}
        for samplePath in samples:
            if "\\" in samplePath:
                fileName = samplePath[samplePath.rindex("\\") + 1:]
            else:
                fileName = samplePath
            sampleBytes[fileName] = open(samplePath, "rb")
        return self.create_voice_bytes(name, sampleBytes)

    def create_voice_bytes(self, name:str, samples: dict[str, BinaryIO]) -> ElevenLabsVoice:
        if len(samples.keys()) == 0:
            raise Exception("Please add at least one sample!")
        if len(samples.keys()) > 25:
            raise Exception("Please only add a maximum of 25 samples.")

        payload = {"name": name}
        files = list()
        for fileName, fileBytes in samples.items():
            files.append(("files", (fileName, fileBytes)))
        response = api_multipart("/voices/add", self._headers, data=payload, filesData=files)
        return self.get_voice_by_ID(response.json()["voice_id"])