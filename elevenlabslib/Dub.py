import concurrent.futures
import threading
from concurrent.futures import Future
from typing import Any

from elevenlabslib import User
from elevenlabslib.helpers import _api_get, _api_del
import time

class Dub:
    def __init__(self, data: dict, linked_user: User, expected_duration_sec: int = -1):
        self._data = data
        self._linked_user = linked_user
        self.dubbing_id = data["dubbing_id"]
        self.name = data["name"]
        self._status = data["status"]
        self.target_languages = data["target_languages"]
        self.error = data.get("error")
        self.expected_duration_sec = expected_duration_sec
        self.creation_time = time.time()

    def fetch_status(self) -> str:
        """
        Updates the status of the dubbing project by fetching the latest metadata.

        Returns:
            str: The updated status of the dubbing project.
        """
        response = _api_get(f"/dubbing/{self.dubbing_id}", headers=self._linked_user.headers)
        self._data = response.json()
        self.error = self._data["error"]
        self._status = self._data["status"]
        return self._status

    def get_transcript(self, language_code: str, format_type: str = "srt") -> str:
        """
        Returns the transcript for the dub as an SRT or WebVTT file.

        Args:
            language_code (str): ID of the language.
            format_type (str, optional): Format to use for the subtitle file, either 'srt' or 'webvtt'. Defaults to 'srt'.

        Returns:
            str: The transcript file contents.
        """
        params = {"format_type": format_type}
        response = _api_get(f"/dubbing/{self.dubbing_id}/transcript/{language_code}", headers=self._linked_user.headers, params=params)
        return response.text

    def get_dubbed_file(self, language_code: str) -> bytes:
        """
        Returns the dubbed file as a streamed file. Videos will be returned in MP4 format and audio-only dubs will be returned in MP3.

        Args:
            language_code (str): ID of the language.

        Returns:
            bytes: The dubbed file contents.
        """
        response = _api_get(f"/dubbing/{self.dubbing_id}/audio/{language_code}", headers=self._linked_user.headers)
        return response.content

    def delete(self) -> None:
        """
        Deletes the dubbing project.
        """
        _api_del(f"/dubbing/{self.dubbing_id}", headers=self._linked_user.headers)

    def get_audio_future(self, language_code: str, check_interval: int = 10) -> concurrent.futures.Future:
        """
        Returns a future that will contain the dubbed file.

        Args:
            language_code (str): ID of the language.
            check_interval (int, optional): Interval in seconds to check for completion if expected_duration_sec is not set. Defaults to 10.

        Returns:
            future: The future that will contain the dubbed file's bytes.
        """
        audio_future = concurrent.futures.Future()
        def wrapped():
            if self.expected_duration_sec > 0:
                elapsed_time = time.time() - self.creation_time
                remaining_time = self.expected_duration_sec - elapsed_time

                if remaining_time > 0:
                    # Wait until 90% of remaining time has passed
                    wait_time = remaining_time * 0.9
                    time.sleep(wait_time)
            cur_stat = self.fetch_status()
            while cur_stat != "dubbed":
                time.sleep(check_interval)
                cur_stat = self.fetch_status()

            audio_data = self.get_dubbed_file(language_code)
            audio_future.set_result(audio_data)
        threading.Thread(target=wrapped).start()
        return audio_future