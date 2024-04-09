from __future__ import annotations
from typing import Dict, Optional, List

from elevenlabslib import User
from elevenlabslib.helpers import _api_del, _api_json, _api_get, _PlayableItem

class PronunciationDictionary:
    """
    Represents a pronunciation dictionary. Can be created manually from stored IDs by using pronunciation_dictionary_from_ids.
    """
    @staticmethod
    def pdict_json_factory(json_data):
        """
        Creates a complete PronunciationDictionary from the JSON data.
        """
        pdict = PronunciationDictionary(json_data.get("id"), json_data.get("version_id"))
        pdict.created_by = json_data.get("created_by")
        pdict.creation_time_unix = json_data.get("creation_time_unix")
        pdict.description = json_data.get("description")
        pdict.name = json_data.get("name")

        return pdict

    def __init__(self, pronunciation_dictionary_id:str, version_id:str):
        self.created_by:Optional[str] = None
        self.creation_time_unix:Optional[str] = None
        self.description:Optional[str] = None
        self.pronunciation_dictionary_id: str = pronunciation_dictionary_id
        self.name:Optional[str] = None
        self.version_id: str = version_id

class Project:
    """
    Contains all the data regarding a project.
    """
    def __init__(self, json_data, linked_user:User):
        self.linkedUser:User = linked_user

        self.project_id:str = json_data.get('project_id')
        self.name:str = json_data.get('name')

        #Updatable information:
        self.can_be_downloaded: bool = json_data.get('can_be_downloaded')
        self.title: Optional[str] = json_data.get('title')
        self.author: Optional[str] = json_data.get('author')
        self.isbn_number: Optional[str] = json_data.get('isbn_number')
        self.volume_normalization = json_data.get('volume_normalization')
        self.state = json_data.get('state')

        self.default_settings: Dict[str, Optional[str]] = {
            'default_title_voice_id': json_data.get('default_title_voice_id'),
            'default_paragraph_voice_id': json_data.get('default_paragraph_voice_id'),
            'default_model_id': json_data.get('default_model_id')
        }

        self.dates: Dict[str, str] = {
            'create_date_unix': json_data.get('create_date_unix'),
            'last_conversion_date_unix': json_data.get('last_conversion_date_unix')
        }


    def update_data(self):
        """
        Updates the project's information.
        """
        response = _api_get(f"/projects/{self.project_id}", headers=self.linkedUser.headers)
        json_data = response.json()
        self.can_be_downloaded: bool = json_data.get('can_be_downloaded')
        self.title: Optional[str] = json_data.get('title')
        self.author: Optional[str] = json_data.get('author')
        self.isbn_number: Optional[str] = json_data.get('isbn_number')
        self.volume_normalization = json_data.get('volume_normalization')
        self.state = json_data.get('state')

        self.default_settings: Dict[str, Optional[str]] = {
            'default_title_voice_id': json_data.get('default_title_voice_id'),
            'default_paragraph_voice_id': json_data.get('default_paragraph_voice_id'),
            'default_model_id': json_data.get('default_model_id')
        }

        self.dates: Dict[str, str] = {
            'create_date_unix': json_data.get('create_date_unix'),
            'last_conversion_date_unix': json_data.get('last_conversion_date_unix')
        }

    def delete(self):
        """
        Deletes the project.
        """
        response = _api_del(f"/projects/{self.project_id}", self.linkedUser.headers)
        self.project_id = ""

    def convert(self):
        """
        Begins the conversion of the project into a snapshot.
        """
        response = _api_json(f"/projects/{self.project_id}/convert", self.linkedUser.headers, jsonData=None)

    def get_chapters(self) -> List[Chapter]:
        """
        Gets the project's chapters.
        """
        response = _api_get(f"/projects/{self.project_id}/chapters", headers=self.linkedUser.headers)
        response_json = response.json()
        chapters = list()
        for chapter_data in response_json["chapters"]:
            chapters.append(Chapter(chapter_data, self))
        return chapters

    def get_chapter_by_id(self, chapter_id:str) -> Chapter:
        """
        Gets a chapter by its ID.
        """
        response = _api_get(f"/projects/{self.project_id}/chapters/{chapter_id}", headers=self.linkedUser.headers)
        chapter_data = response.json()
        return Chapter(chapter_data, self)

    def get_snapshots(self) -> List[ProjectSnapshot]:
        """
        Gets the project's snapshots (audio versions).
        """
        self.update_data()
        if not self.can_be_downloaded:
            return []   #No snapshots available.
        response = _api_get(f"/projects/{self.project_id}/snapshots", headers=self.linkedUser.headers)
        response_json = response.json()
        snapshots = list()
        for snapshot_data in response_json["snapshots"]:
            snapshots.append(ProjectSnapshot(snapshot_data, self))
        return snapshots

    def get_snapshot_by_id(self, project_snapshot_id:str) -> ProjectSnapshot:
        """
        Gets a snapshot of the project by ID.
        """
        snapshots = self.get_snapshots()
        for snapshot in snapshots:
            if snapshot.project_snapshot_id == project_snapshot_id:
                return snapshot

        raise ValueError(f"No snapshot with id {project_snapshot_id} found!")

    def update_pronunciation_dictionaries(self, pronunciation_dictionaries:List[PronunciationDictionary]):
        payload = {
            "pronunciation_dictionary_locators": [
                    {"pronunciation_dictionary_id":pdict.pronunciation_dictionary_id,
                     "version_id":pdict.version_id}
                for pdict in pronunciation_dictionaries
            ]
        }
        response = _api_json(f"/projects/{self.project_id}/update-pronunciation-dictionaries", headers=self.linkedUser.headers, jsonData=payload)



class Chapter:
    def __init__(self, json_data, parent_project:Project):
        self.project:Project = parent_project
        self.chapter_id:str = json_data.get('chapter_id')
        self.name:str = json_data.get('name')
        self.last_conversion_date_unix:Optional[str] = json_data.get('last_conversion_date_unix')
        self.conversion_progress:Optional[str] = json_data.get('conversion_progress')
        self.can_be_downloaded:bool = json_data.get('can_be_downloaded')
        self.state:str = json_data.get('state')

        self.statistics:Optional[Dict[str, str]] = json_data.get('statistics')

    def update_data(self):
        """
        Updates the chapter's data.
        """
        response = _api_get(f"/projects/{self.project.project_id}/chapters/{self.chapter_id}", headers=self.project.linkedUser.headers)
        json_data = response.json()
        self.name: str = json_data.get('name')
        self.last_conversion_date_unix: Optional[str] = json_data.get('last_conversion_date_unix')
        self.conversion_progress: Optional[str] = json_data.get('conversion_progress')
        self.can_be_downloaded: bool = json_data.get('can_be_downloaded')
        self.state: str = json_data.get('state')
        self.statistics: Optional[Dict[str, str]] = json_data.get('statistics')

    def delete(self):
        """
        Deletes the chapter.
        """
        response = _api_del(f"/projects/{self.project.project_id}/chapters/{self.chapter_id}", self.project.linkedUser.headers)
        self.chapter_id = ""

    def convert(self):
        """
        Begins the conversion of the chapter into a snapshot.
        """
        response = _api_json(f"/projects/{self.project.project_id}/chapters/{self.chapter_id}/convert", self.project.linkedUser.headers, jsonData=None)

    def get_snapshots(self) -> List[ChapterSnapshot]:
        """
        Gets the chapter's snapshots (audio versions).
        """
        self.update_data()
        if not self.can_be_downloaded:  #No snapshots are available.
            return []

        response = _api_get(f"/projects/{self.project.project_id}/chapters/{self.chapter_id}/snapshots", headers=self.project.linkedUser.headers)

        response_json = response.json()
        chapter_snapshots = list()
        for chapter_snapshot_data in response_json["snapshots"]:
            chapter_snapshots.append(ChapterSnapshot(chapter_snapshot_data, self))
        return chapter_snapshots

    def get_snapshot_by_id(self, chapter_snapshot_id: str) -> ChapterSnapshot:
        """
        Gets a snapshot of the chapter by ID.
        """
        chapter_snapshots = self.get_snapshots()
        for chapter_snapshot in chapter_snapshots:
            if chapter_snapshot.chapter_snapshot_id == chapter_snapshot_id:
                return chapter_snapshot

        raise ValueError(f"No snapshot with id {chapter_snapshot_id} found!")

class ProjectSnapshot(_PlayableItem):
    def __init__(self, json_data, parent_project: Project):
        super().__init__()
        self.project:Project = parent_project
        self.project_snapshot_id:str = json_data.get('project_snapshot_id')
        self.created_at_unix:str = json_data.get('created_at_unix')
        self.name:str = json_data.get('name')

    def get_audio_bytes(self) -> bytes:
        return self._fetch_and_cache_audio(lambda: _api_json(f"/projects/{self.project.project_id}/snapshots/{self.project_snapshot_id}/stream", self.project.linkedUser.headers, jsonData=None))



class ChapterSnapshot(_PlayableItem):
    def __init__(self, json_data, parent_chapter: Chapter):
        super().__init__()
        self.chapter:Chapter = parent_chapter
        self.chapter_snapshot_id:str = json_data.get('chapter_snapshot_id')
        self.created_at_unix:str = json_data.get('created_at_unix')
        self.name:str = json_data.get('name')

    def get_audio_bytes(self) -> bytes:
        return self._fetch_and_cache_audio(lambda: _api_json(f"/projects/{self.chapter.project.project_id}/chapters/{self.chapter.chapter_id}/snapshots/{self.chapter_snapshot_id}/stream", self.chapter.project.linkedUser.headers, jsonData=None))


