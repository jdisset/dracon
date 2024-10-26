from typing import Optional, Any
import re
from pydantic import BaseModel
from enum import Enum
from dracon.utils import dict_like, DictLike, ListLike, ftrace, deepcopy, list_like
from dracon.nodes import (
    MergeNode,
    DraconMappingNode,
    DraconSequenceNode,
    IncludeNode,
)
from ruamel.yaml.nodes import Node
from dracon.keypath import KeyPath


def make_default_empty_mapping_node():
    return DraconMappingNode(
        tag='',
        value=[],
    )


@ftrace(inputs=False, watch=[])
def process_merges(comp_res):
    comp_res.find_special_nodes('merge', lambda n: isinstance(n, MergeNode))
    comp_res.sort_special_nodes('merge')

    for merge_path in comp_res.pop_all_special('merge'):
        merge_path = merge_path.removed_mapping_key()
        merge_node = merge_path.get_obj(comp_res.root)
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

        assert node_key in parent_node, f'Key {node_key} not found in parent node'

        key_node = parent_node.get_key(
            node_key
        )  # the scalar node that contains the merge instruction
        assert isinstance(
            key_node, MergeNode
        ), f'Invalid merge node type: {type(key_node)} at {node_key}. {merge_path=}'

        try:
            merge_key = MergeKey(raw=key_node.merge_key_raw)
        except Exception as e:
            raise ValueError(
                'While processing merge node',
                merge_node.start_mark,
                f'Error: {str(e)}',
            ) from e
        # we want to do parent_node = merged(parent_node, merge_node, merge_key)

        del parent_node[node_key]

        if merge_key.keypath:
            parent_path = parent_path + KeyPath(merge_key.keypath)

        new_parent = parent_path.get_obj(comp_res.root)

        new_parent = merged(new_parent, merge_node, merge_key)
        assert isinstance(new_parent, Node)
        comp_res.replace_node_at(parent_path, new_parent)

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
    keypath: Optional[str] = None

    @staticmethod
    def is_merge_key(key: str) -> bool:
        return key.startswith('<<')

    def get_mode_priority(
        self,
        mode_str: str,
        default_mode=MergeMode.APPEND,
        default_priority=MergePriority.EXISTING,
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

        # check if it has a keypath part (anything after @)
        default_dict_priority = MergePriority.EXISTING
        default_dict_mode = MergeMode.APPEND
        default_list_priority = MergePriority.EXISTING
        default_list_mode = MergeMode.REPLACE

        keypath_str = re.search(r'@(.+)', self.raw)
        if keypath_str:  # it's an @ keypath, aka an override
            self.keypath = keypath_str.group(1)
            # by default, we override with the new value
            default_dict_priority = MergePriority.NEW
            default_list_priority = MergePriority.NEW

        dict_str = re.search(r'{(.+)}', self.raw)
        if dict_str:
            dict_str = dict_str.group(1)
        else:
            dict_str = ''

        self.dict_mode, self.dict_priority, self.dict_depth = self.get_mode_priority(
            dict_str, default_mode=default_dict_mode, default_priority=default_dict_priority
        )

        list_str = re.search(r'\[(.+)\]', self.raw)
        if list_str:
            list_str = list_str.group(1)
        else:
            list_str = ''
        self.list_mode, self.list_priority, self.list_depth = self.get_mode_priority(
            list_str, default_mode=default_list_mode, default_priority=default_list_priority
        )


DEFAULT_ADD_TO_CONTEXT_MERGE_KEY = MergeKey(raw='<<{+<}[~<]')


def add_to_context(context, item, merge_key=DEFAULT_ADD_TO_CONTEXT_MERGE_KEY):
    if hasattr(item, 'context'):
        item.context = merged(item.context, context, merge_key)


def merged(existing: Any, new: Any, k: MergeKey) -> DictLike:
    def merge_value(v1: Any, v2: Any, depth: int = 0) -> Any:
        if type(v1) is type(v2) and hasattr(v1, 'merged_with') and hasattr(v2, 'merged_with'):
            return v1.merged_with(v2, depth + 1)
        elif dict_like(v1) and dict_like(v2):
            return merge_dicts(v1, v2, depth + 1)
        elif list_like(v1) and list_like(v2):
            return merge_lists(v1, v2, depth + 1)
        else:
            return v1 if k.dict_priority == MergePriority.EXISTING else v2

    def merge_dicts(dict1: DictLike, dict2: DictLike, depth: int = 0) -> DictLike:
        pdict, other = (
            (dict1, dict2) if k.dict_priority == MergePriority.EXISTING else (dict2, dict1)
        )

        if k.dict_depth is not None and depth > k.dict_depth:
            return pdict

        result = pdict.copy()

        if hasattr(pdict, 'tag') and hasattr(other, 'tag'):
            # we're dealing with nodes
            if pdict.tag.startswith('!'):
                result.tag = pdict.tag
            elif other.tag.startswith('!'):
                result.tag = other.tag

        for key, value in other.items():
            if key not in result:
                result[key] = value
            elif k.dict_mode == MergeMode.APPEND:
                result[key] = (
                    merge_value(result[key], value, depth + 1)
                    if k.dict_priority == MergePriority.EXISTING
                    else merge_value(value, result[key], depth + 1)
                )
        return result

    def merge_lists(list1: ListLike, list2: ListLike, depth: int = 0) -> ListLike:
        if (k.list_depth is not None and depth > k.list_depth) or k.list_mode == MergeMode.REPLACE:
            return list1 if k.list_priority == MergePriority.EXISTING else list2
        return list1 + list2 if k.list_priority == MergePriority.EXISTING else list2 + list1

    return merge_value(existing, new)


# ideal syntax:
# <<{>~}(attr1,attr2{+<}[+](subattr{~})): "value"
