from __future__ import annotations

import logging
from typing import BinaryIO, Optional

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from elevenlabslib.ElevenLabsSample import ElevenLabsSample

from elevenlabslib.ElevenLabsUser import ElevenLabsUser
from elevenlabslib.helpers import *

class ElevenLabsVoice:
    def __init__(self, voiceData, linkedUser:ElevenLabsUser):
        self._linkedUser = linkedUser
        # This is the name at the time the object was created. It won't be updated.
        # (Useful to iterate over all voices to find one with a specific name without spamming the API)
        self.initialName = voiceData["name"]
        self._voiceID = voiceData["voice_id"]
        self._category = voiceData["category"]
        self._previewURL = voiceData["preview_url"]

    #The reasoning behind only providing this method is that I don't want to do too much with the library.
    #It's only a way to call the API more easily. Saving files, conversion etc is up to the implementation.
    def generate_audio_bytes(self, prompt:str, stability:Optional[float]=None, similarity_boost:Optional[float]=None) -> bytes:
        #The output from the site is an mp3 file.
        #You can check the README for an example of how to convert it to wav on the fly using pydub and bytesIO.
        payload = {"text": prompt}
        if stability is not None or similarity_boost is not None:
            existingSettings = self.get_settings()
            if stability is None: stability = existingSettings["stability"]
            if similarity_boost is None: stability = existingSettings["similarity_boost"]
            if not (stability <= 1 and similarity_boost <= 1):
                raise ValueError("Please provide a value equal or below 1.")
            payload["voice_settings"] = dict()
            payload["voice_settings"]["stability"] = stability
            payload["voice_settings"]["similarity_boost"] = similarity_boost
        try:
            response = api_json("/text-to-speech/" + self._voiceID + "/stream", self._linkedUser.headers, jsonData=payload)
        except Exception as e:
            logging.exception(e)
            raise e

        return response.content

    def get_samples(self) -> list[ElevenLabsSample]:
        response = api_get("/voices/" + self._voiceID, self._linkedUser.headers)
        outputList = list()
        samplesData = response.json()["samples"]
        from elevenlabslib.ElevenLabsSample import ElevenLabsSample
        for sampleData in samplesData:
            outputList.append(ElevenLabsSample(sampleData, self))
        return outputList

    def get_voice_preview_bytes(self) -> bytes:
        response = requests.get(self._previewURL, allow_redirects=True)
        return response.content


    def get_settings(self) -> dict:
        # We don't store the name OR the settings, as they can be changed externally.
        response = api_get("/voices/" + self._voiceID + "/settings", self._linkedUser.headers)
        return response.json()

    def get_name(self) -> str:
        response = api_get("/voices/" + self._voiceID, self._linkedUser.headers)

        return response.json()["name"]

    def edit_settings(self, stability:float=None, similarity_boost:float=None):
        if stability is None or similarity_boost is None:
            oldSettings = self.get_settings()
            if stability is None: stability = oldSettings["stability"]
            if similarity_boost is None: stability = oldSettings["similarity_boost"]

        if not(stability <= 1 and similarity_boost <= 1):
            raise ValueError("Please input a value that is less than or equal to 1.")
        payload = {"stability": stability, "similarity_boost": similarity_boost}
        api_json("/voices/" + self._voiceID + "/settings/edit", self._linkedUser.headers, jsonData=payload)

    def edit_name(self, newName:str):
        payload = {"name":newName}
        api_multipart("/voices/" + self._voiceID + "/edit", self._linkedUser.headers, data=payload)

    def add_samples_by_path(self, samples:list[str]):
        sampleBytes = {}
        for samplePath in samples:
            if "\\" in samplePath:
                fileName = samplePath[samplePath.rindex("\\")+1:]
            else:
                fileName = samplePath
            sampleBytes[fileName] = open(samplePath, "rb")
        self.add_samples_bytes(sampleBytes)

    #Requires a dict of filenames and bytes
    def add_samples_bytes(self, samples:dict[str, BinaryIO]):
        if len(samples.keys()) == 0:
            raise Exception("Please add at least one sample!")

        payload = {"name":self.get_name()}
        files = list()
        for fileName, fileBytes in samples.items():
            files.append(("files", (fileName, fileBytes)))

        api_multipart("/voices/" + self._voiceID + "/edit", self._linkedUser.headers, data=payload, filesData=files)

    def delete_voice(self):
        if self._category == "premade":
            raise Exception("Cannot delete premade voices!")
        response = api_del("/voices/"+self._voiceID, self._linkedUser.headers)
        self._voiceID = ""

    @property
    def previewURL(self):
        return self._previewURL

    @property
    def category(self):
        return self._category

    # Since the same voice can be available for multiple users, we allow the user to change which API key is used.
    @property
    def linkedUser(self):
        return self._linkedUser

    @linkedUser.setter
    def linkedUser(self, newUser: ElevenLabsUser):
        self._linkedUser = newUser

    @property
    def voiceID(self):
        return self._voiceID