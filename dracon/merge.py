from typing import Callable, Type, Dict, Union, Optional, Any, List
from copy import deepcopy
import re
from typing import Optional
from pydantic import BaseModel
from enum import Enum
from dracon.utils import dict_like, list_like, DictLike, ListLike
from dracon.composer import MergeNode, DraconComposer, CompositionResult


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


def process_merges(comp_res: CompositionResult):

    while comp_res.merge_nodes:

        merge_path = comp_res.merge_nodes.pop()
        merge_node = merge_path.get_obj(comp_res.root)

        assert isinstance(merge_node, MergeNode), f'Invalid merge node type: {type(merge_node)}'

        parent_path = merge_path.copy().up()
        node_key = merge_path[-1]
        parent_node = parent_path.get_obj(comp_res.root)

        if not dict_like(parent_node):
            raise ValueError(
                'While processing merge node',
                merge_node.start_mark,
                'Parent of merge node must be a dictionary',
                f'but got {type(parent_node)} at {parent_node.start_mark}',
            )
        # we want to do parent_node = merged(parent_node, merge_node, merge_key)
        new_parent = parent_node.copy()
        del new_parent[node_key]

        try:
            merge_key = MergeKey(raw=merge_node.merge_key_raw)
        except Exception as e:
            raise ValueError(
                'While processing merge node',
                merge_node.start_mark,
                f'Error: {str(e)}',
            )

        new_parent = merged(new_parent, merge_node, merge_key)
        comp_res.replace_node_at(parent_path, new_parent)

        comp_res.merge_nodes.remove(merge_path)

    return comp_res


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


def merged(existing: DictLike[str, Any], new: DictLike[str, Any], k: MergeKey) -> DictLike[str, Any]:

    # 1 is existing, 2 is new

    def merge_value(v1: Any, v2: Any, depth: int = 0) -> Any:
        if isinstance(v1, DictLike) and isinstance(v2, DictLike):
            return merge_dicts(v1, v2, depth + 1)
        # If both values are lists, merge them
        elif isinstance(v1, ListLike) and isinstance(v2, ListLike):
            return merge_lists(v1, v2, depth + 1)
        # For other types, return based on the priority
        else:
            return v1 if k.dict_priority == MergePriority.EXISTING else v2

    def merge_dicts(dict1: DictLike[str, Any], dict2: DictLike[str, Any], depth: int = 0) -> DictLike[str, Any]:
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

    def merge_lists(list1: ListLike[Any], list2: ListLike[Any], depth: int = 0) -> ListLike[Any]:
        if (k.list_depth is not None and depth > k.list_depth) or k.list_mode == MergeMode.REPLACE:
            return list1 if k.list_priority == MergePriority.EXISTING else list2
        if k.list_priority == MergePriority.EXISTING:
            return list1 + list2
        return list2 + list1

    # Start the merge process with the top-level dictionaries
    return merge_dicts(existing, new)

