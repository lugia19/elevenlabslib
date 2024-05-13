from __future__ import annotations
from typing import Dict, Optional, List, Union

import xmltodict

from elevenlabslib import User
from elevenlabslib.helpers import _api_del, _api_json, _api_get, _PlayableItem


class PronunciationDictionary:
    """
    Represents a pronunciation dictionary. Can be created manually from stored IDs by using pronunciation_dictionary_from_ids.
    """
    def __init__(self, dictionary_data:dict, linked_user:User):
        self.pronunciation_dictionary_id: str = dictionary_data["id"]
        self.name: Optional[str] = dictionary_data["name"]
        self.description: Optional[str] = dictionary_data["description"]
        self.created_by:Optional[str] = dictionary_data["created_by"]
        self.creation_time_unix:Optional[str] = dictionary_data["creation_time_unix"]
        self.version_id: str
        if "version_id" in dictionary_data:
            self.version_id = dictionary_data["version_id"]
        else:
            self.version_id = dictionary_data["latest_version_id"]
        self._linked_user = linked_user

    def download_dictionary(self, version_id:str = None) -> str:
        """
        This function returns a PLS file for the specified version_id (or the latest).

        Args:
            version_id (str, Optional): The specific dictionary version to download. Defaults to the latest.
        Returns:
            str: The PLS file as a string.
        """
        if not version_id:
            version_id = self.version_id

        response = _api_get(f"/pronunciation-dictionaries/{self.pronunciation_dictionary_id}/{version_id}/download", headers=self._linked_user.headers)

        return response.text

    def get_rules(self, version_id:str = None) -> List[PronunciationRule]:
        """
        This function returns the list of rules the specified version_id (or the latest).

        Args:
            version_id (str, Optional): The specific dictionary version. Defaults to the latest.
        Returns:
            List[PronunciationRule]: A list containing the rules.
        """
        dictionary_text = self.download_dictionary(version_id)
        rule_list = list()
        dictionary_dict = xmltodict.parse(dictionary_text)
        if "lexeme" not in dictionary_dict["lexicon"]:
            return []
        if isinstance(dictionary_dict["lexicon"]["lexeme"], dict):
            return [PronunciationRule.rule_factory(dictionary_dict["lexicon"]["lexeme"])]
        for rule_data in dictionary_dict["lexicon"]["lexeme"]:
            rule_list.append(PronunciationRule.rule_factory(rule_data))

        return rule_list

    def add_rules(self, new_rules:Union[PronunciationRule, List[PronunciationRule]]):
        """
        Adds new rules to the dictionary.
        Args:
            new_rules (PronunciationRule|List[PronunciationRule]): The rules to add.
        Returns:
            str: The new versionID of the dictionary.
        """
        if isinstance(new_rules, PronunciationRule):
            new_rules = [new_rules]
        payload = {"rules": [x.to_dict() for x in new_rules]}
        response = _api_json(f"/pronunciation-dictionaries/{self.pronunciation_dictionary_id}/add-rules", jsonData=payload, headers=self._linked_user.headers)
        self.version_id = response.json()["version_id"]

        return self.version_id

    def remove_rules(self, rules_to_remove:Union[PronunciationRule, List[PronunciationRule], str, List[str]]):
        """
        Removes rules from the dictionary.
        Args:
            rules_to_remove (PronunciationRule|List[PronunciationRule]|str|List[str]): The rules to remove, either as objects or by their string_to_replace.
        Returns:
            str: The new versionID of the dictionary.
        """
        grapheme_list = list()
        if isinstance(rules_to_remove, PronunciationRule) or isinstance(rules_to_remove, str):
            rules_to_remove = [rules_to_remove]
        for rule in rules_to_remove:
            if isinstance(rule, str):
                grapheme_list.append(rule)
            elif isinstance(rule, PronunciationRule):
                grapheme_list.append(rule.string_to_replace)
        payload = {"rule_strings" : grapheme_list}

        response = _api_json(f"/pronunciation-dictionaries/{self.pronunciation_dictionary_id}/remove-rules", jsonData=payload, headers=self._linked_user.headers)
        self.version_id = response.json()["version_id"]

        return self.version_id

class PronunciationRule:
    @staticmethod
    def rule_factory(rule_data) -> PronunciationRule:
        if "phoneme" in rule_data:
            return PhonemeRule(rule_data["grapheme"], rule_data["phoneme"]["@alphabet"], rule_data["phoneme"]["#text"])
        else:
            return AliasRule(rule_data["grapheme"], rule_data["alias"])

    def __init__(self, string_to_replace):
        self.type = None
        self.string_to_replace = string_to_replace

    def to_dict(self) -> dict:
        pass
class AliasRule(PronunciationRule):
    def __init__(self, string_to_replace, alias):
        super().__init__(string_to_replace)
        self.type = "alias"
        self.alias = alias

    def to_dict(self) -> dict:
        data_dict = dict()
        data_dict["type"] = self.type
        data_dict["string_to_replace"] = self.string_to_replace
        data_dict["alias"] = self.alias

        return data_dict
class PhonemeRule(PronunciationRule):
    def __init__(self, string_to_replace, alphabet, phoneme):
        super().__init__(string_to_replace)
        self.type = "phoneme"
        self.alphabet = alphabet
        self.phoneme = phoneme

    def to_dict(self) -> dict:
        data_dict = dict()
        data_dict["type"] = self.type
        data_dict["string_to_replace"] = self.string_to_replace
        data_dict["alphabet"] = self.alphabet
        data_dict["phoneme"] = self.phoneme
        return data_dict