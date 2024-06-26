from typing import Callable, Type, Dict, Union, Optional, Any, List
from copy import deepcopy
import re
from typing import Optional
from pydantic import BaseModel
from enum import Enum
from dracon.utils import dict_like


def perform_merges(conf_obj):
    if isinstance(conf_obj, list):
        return [perform_merges(v) for v in conf_obj]

    if dict_like(conf_obj):
        res = {}
        merges = []
        for key, value in conf_obj.items():
            if hasattr(key, 'tag') and key.tag == 'dracon_merge':
                merges.append((MergeKey(raw=key.value), value))
            else:
                res[key] = perform_merges(value)
        for merge_key, merge_value in merges:
            res = merged(res, merge_value, merge_key)
        return res

    return conf_obj


class MergeMode(Enum):
    # -> in the case of two dictionaries, append new keys
    # and will recursively merge subdict keys
    # when same keys are leaves and not dictionaries, see priority
    # when keys are lists, see list_mode
    # -> in the case of two lists, append new items
    APPEND = 'append'  # symbol: +

    # -> in the case of two dictionaries,
    # fully replace conflicting keys and append new keys
    # -> in the case of two lists, replace the whole list
    REPLACE = 'replace'  # symbol: ~


class MergePriority(Enum):
    NEW = 'new'  # symbol: <
    EXISTING = 'existing'  # symbol: >


class MergeKey(BaseModel):
    raw: str
    dict_mode: MergeMode = MergeMode.APPEND
    dict_priority: MergePriority = MergePriority.EXISTING
    dict_depth: Optional[int] = None
    list_mode: MergeMode = MergeMode.REPLACE
    list_priority: MergePriority = MergePriority.EXISTING
    list_depth: Optional[int] = None

    @staticmethod
    def is_merge_key(key: str) -> bool:
        return key.startswith('<<')

    def get_mode_priority(
        self, mode_str: str, default_mode=MergeMode.APPEND, default_priority=MergePriority.EXISTING
    ):
        # + means RECURSE or APPEND
        # ~ means REPLACE
        # > means EXISTING
        # < means NEW
        mode, priority = default_mode, default_priority
        assert (
            '+' not in mode_str or '~' not in mode_str
        ), 'Only one of + or ~ is allowed in dict_mode'
        if '+' in mode_str:
            mode = MergeMode.APPEND
        if '~' in mode_str:
            mode = MergeMode.REPLACE
        assert (
            '>' not in mode_str or '<' not in mode_str
        ), 'Only one of > or < is allowed in dict_priority'
        if '>' in mode_str:
            priority = MergePriority.EXISTING
        if '<' in mode_str:
            priority = MergePriority.NEW

        depth = None
        depth_str = re.search(r'(\d+)', mode_str)
        if depth_str:
            depth = int(depth_str.group(1))

        return mode, priority, depth

    def model_post_init(self, *args, **kwargs):
        # to find the dict_mode and list_mode, we need to parse the raw key
        # things inside {} concern the dict_mode and priority
        # things inside [] concern the list_mode and priority

        super().model_post_init(*args, **kwargs)

        # check that only zero or one [] and {} are present
        assert self.raw.count('{') <= 1, 'Only one {} is allowed in merge key'
        assert self.raw.count('[') <= 1, 'Only one [] is allowed in merge key'
        # check that they close properly
        assert self.raw.count('{') == self.raw.count('}'), 'Mismatched {} in merge key'
        assert self.raw.count('[') == self.raw.count(']'), 'Mismatched [] in merge key'

        dict_str = re.search(r'{(.+)}', self.raw)
        if dict_str:
            dict_str = dict_str.group(1)
            self.dict_mode, self.dict_priority, self.dict_depth = self.get_mode_priority(
                dict_str, self.dict_mode, self.dict_priority
            )

        list_str = re.search(r'\[(.+)\]', self.raw)
        if list_str:
            list_str = list_str.group(1)
            self.list_mode, self.list_priority, self.list_depth = self.get_mode_priority(
                list_str, self.list_mode, self.list_priority
            )


def merged(existing: Dict[str, Any], new: Dict[str, Any], k: MergeKey) -> Dict[str, Any]:

    # 1 is existing, 2 is new

    def merge_value(v1: Any, v2: Any, depth: int = 0) -> Any:
        if isinstance(v1, dict) and isinstance(v2, dict):
            return merge_dicts(v1, v2, depth + 1)
        # If both values are lists, merge them
        elif isinstance(v1, list) and isinstance(v2, list):
            return merge_lists(v1, v2, depth + 1)
        # For other types, return based on the priority
        else:
            return v1 if k.dict_priority == MergePriority.EXISTING else v2

    def merge_dicts(dict1: Dict[str, Any], dict2: Dict[str, Any], depth: int = 0) -> Dict[str, Any]:
        pdict, other = (
            (dict1, dict2) if k.dict_priority == MergePriority.EXISTING else (dict2, dict1)
        )

        if k.dict_depth is not None and depth > k.dict_depth:
            return pdict

        result = deepcopy(pdict)

        for key, value in other.items():
            if key not in result:  # If the key doesn't exist in result, add it
                result[key] = value
            elif k.dict_mode == MergeMode.APPEND:
                if k.dict_priority == MergePriority.EXISTING:
                    result[key] = merge_value(result[key], value, depth + 1)
                else:
                    result[key] = merge_value(value, result[key], depth + 1)
        return result

    def merge_lists(list1: List[Any], list2: List[Any], depth: int = 0) -> List[Any]:
        if (k.list_depth is not None and depth > k.list_depth) or k.list_mode == MergeMode.REPLACE:
            return list1 if k.list_priority == MergePriority.EXISTING else list2
        if k.list_priority == MergePriority.EXISTING:
            return list1 + list2
        return list2 + list1

    # Start the merge process with the top-level dictionaries
    return merge_dicts(existing, new)
