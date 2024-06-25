import os
from pathlib import Path
from yaml.constructor import ConstructorError
from copy import deepcopy
from typing import Callable, Type
import os
import re
from rich import print as rprint
from pydantic import BaseModel
from typing import List
from collections import namedtuple
from enum import Enum
from typing import List, Dict, Any, Union, Optional
from pathlib import Path


## {{{                       --     random utils     --

import xxhash
import base64


def dict_like(obj) -> bool:
    return (
        hasattr(obj, 'keys')
        and hasattr(obj, 'get')
        and hasattr(obj, '__getitem__')
        and hasattr(obj, '__contains__')
        and hasattr(obj, '__iter__')
        and hasattr(obj, 'items')
    )


def with_indent(content: str, indent: int) -> str:
    return '\n'.join([f'{" " * indent}{line}' for line in content.split('\n')])


def get_hash(data: str) -> str:
    hash_value = xxhash.xxh128(data).digest()
    return base64.b32encode(hash_value).decode('utf-8').rstrip('=')


##────────────────────────────────────────────────────────────────────────────}}}
## {{{                     --     raw dict updater     --

# TODO: maybe modify to make it work better with the merge key model


def replace(d1, d2):
    return deepcopy(d2)


def extend(d1, d2):
    if d1 is None:
        return deepcopy(d2)
    if d2 is None:
        return deepcopy(d1)
    return deepcopy(d2) + deepcopy(d1)


DEFAULT_MERGE_MODES = {'replace': replace, 'extend': extend, 'auto': 'auto'}


def maybecopy(obj, deep: bool = True):
    return deepcopy(obj) if deep else obj


def updated_dict(
    d1,
    d2,
    merge_mode: Optional[Dict[Union[Type, str], Union[str, Callable]]] = None,
    deep: bool = True,
) -> Dict:

    if merge_mode is None:
        merge_mode = {}

    t1, t2 = type(d1), type(d2)
    st1, st2 = str(t1.__name__), str(t2.__name__)

    mmode = 'auto'

    if t1 in merge_mode or st1 in merge_mode:
        mmode = merge_mode.get(t1, merge_mode.get(st1))
        if mmode in DEFAULT_MERGE_MODES:
            mmode = DEFAULT_MERGE_MODES[mmode]
        if callable(mmode):
            return mmode(d1, d2)

    if t2 in merge_mode or st2 in merge_mode:
        mmode = merge_mode.get(t2, merge_mode.get(st2))
        if mmode in DEFAULT_MERGE_MODES:
            mmode = DEFAULT_MERGE_MODES[mmode]
        if callable(mmode):
            return mmode(d1, d2)

    if mmode == 'auto':
        if not dict_like(d1):
            return maybecopy(d2, deep) if d2 is not None else maybecopy(d1, deep)
        if not dict_like(d2):
            return maybecopy(d1, deep) if d1 is not None else maybecopy(d2, deep)
    else:
        raise NotImplementedError(f'Cannot merge {t1} and {t2}')

    assert mmode == 'auto', f'Invalid merge mode {mmode}'
    # they're both dicts:
    res = {}
    for key, val in d1.items():
        if key in d2:
            res[key] = updated_dict(d1[key], d2[key], merge_mode)
        else:
            res[key] = maybecopy(d1[key], deep)
    for key, val in d2.items():
        if not key in d1:
            res[key] = maybecopy(val, deep)
    return res


##────────────────────────────────────────────────────────────────────────────}}}
## {{{                       --     merge things     --


"""
    # Syntax Overview

    The enhanced merge notation allows for flexible and powerful merging strategies, with options for specifying list and dictionary merge behaviors, depth limits, and priority settings. The merge options can be combined within `{...}` brackets.

    ## Merge Operators

    1. **Vanilla Merge (`<<:`)**
       - Default YAML merge, where the values from the introduced dictionary are merged into the current dictionary, and current dictionary keys take precedence in case of conflicts.

    2. **Enhanced Merge (`<<[options]{options}`)**
       - Augment the YAML merge syntax with additional merging preference options using a well-defined list of symbols:
         - **List Merge Options:**
           - `+`: Extend lists and/or dictionaries recursively (unless depth modifier is specified, in which case it will extend until that depth and then replace).
           - `~`: Replace dictionaries or lists entirely.
         - **Priority Options:**
           - `<`: Introduced dictionary takes precedence.
           - `>`: Existing dictionary takes precedence.
         - **Depth Limit:**
           - `+N`: Merge dictionaries up to `N` depth levels.
         - **Repeating Merge:**
           - `*`: Repeat merge for each item in a list/dict and define the `${!index}`, `${!key}`, and `${!value}` variables for the scope.

    ## Examples

    ### Example 1: Basic Merge with Priority Setting

    ```yaml
    base: &base
      setting1: baseval
      setting2: baseval2

    config:
      setting1: newval
      <<{>}: *base  # Existing keys in `config` take precedence
    ```

    ### Example 2: Merge with List-Specific and Dict-Specific Notations

    #### Priority on Introduced Dictionary (Lists are extended)

    ```yaml
    config:
      list1: [1, 2, 3]
      <<[+]{<}: *pkg:configs/list_config  # Introduced keys take precedence, lists are extended
    ```

    #### Priority on Existing Dictionary (Lists are replaced)

    ```yaml
    config:
      list1: [1, 2, 3]
      <<[~]{>}: *pkg:configs/list_config  # Existing keys take precedence, lists are replaced
    ```

    ### Example 3: Merge with Depth-Limited Notation

    #### Priority on Introduced Dictionary (Merge up to one depth level)

    ```yaml
    config:
      setting1: newval
      <<{+1<}: *base  # Introduced keys take precedence, merge only up to one depth level
    ```

    #### Priority on Existing Dictionary (Merge up to one depth level)

    ```yaml
    config:
      setting1: newval
      <<{+1>}: *base  # Existing keys take precedence, merge only up to one depth level
    ```

    ### Example 4: Combining List-Specific, Dict-Specific, Depth-Limited, and Priority Notations

    ```yaml
    config:
      setting1: newval
      list1: [1, 2, 3]
      dict1:
        subkey1: subval1
      <<[+]{+2<}: *base  # Introduced keys take precedence, extend lists, merge dicts up to two levels
    ```

    ### Example 5: Repeating Merge for Each Item in a List/Dict

    ```yaml
    repeat_merge:
      <<[*]{<}:
        data_items:
          - id: ${!index}
            name: item_${!index}
    ```

    ## Combining Options

    You can combine any dict arguments by putting all of them inside `{}`. For example:

    - `{+<1}`: Merge dictionaries up to one depth level, extend lists, and the introduced dictionary takes precedence.
    - `{<+}`: The introduced dictionary takes precedence, and lists are extended.
    - `{~>}`: Replace lists and dictionaries entirely, and the existing dictionary takes precedence.

"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel


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


def merged(d1: dict, d2: dict, k: MergeKey) -> dict:
    # TODO
    ...


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                    --     loaders + include     --


class ConfPathLoader(BaseModel):

    def load_raw(self, path: str):
        raise NotImplementedError

    def with_yaml_ext(self, path: str) -> str:
        if not path.endswith('.yaml'):
            return path + '.yaml'
        return path


class FileConfPathLoader(ConfPathLoader):
    def load_raw(self, path: str):
        p = Path(self.with_yaml_ext(path)).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f'File not found: {p}')
        with open(p, 'r') as f:
            return f.read()


class PkgConfPathLoader(ConfPathLoader):
    def load_raw(self, path: str):
        import importlib.resources
        from importlib.resources import files, as_file

        pkg = __name__
        if ':' in path:
            pkg, path = path.split(':', 1)

        fpath = self.with_yaml_ext(path)
        try:
            with as_file(files(pkg) / fpath) as p:
                with open(p, 'r') as f:
                    return f.read()
        except FileNotFoundError:
            raise FileNotFoundError(f'File not found in package {pkg}: {fpath}')


def load_raw_conf_str(path: str, escape_keys=None) -> str:
    ctype = 'file'
    cpath = path
    raw_yaml = None
    if ':' in path:
        ctype, cpath = path.split(':', 1)
    if ctype == 'file':
        raw_yaml = FileConfPathLoader().load_raw(cpath)
    elif ctype == 'pkg':
        raw_yaml = PkgConfPathLoader().load_raw(cpath)
    else:
        raise ValueError(f'Unknown include type: {ctype}')
    if escape_keys:

        def replace_merge(match):
            return match.group(0).replace(match.group(1), '"' + match.group(1) + '"')

        for key in escape_keys:
            pattern = re.compile(r'^\s*(' + key + r')\s*:\s*$', re.MULTILINE)
            raw_yaml = pattern.sub(replace_merge, raw_yaml)
    return raw_yaml


class IncludePath(BaseModel):
    path: str
    subpath: Optional[str] = None

    def model_post_init(self, *args, **kwargs):
        super().model_post_init(*args, **kwargs)
        if '@' in self.path:
            assert self.path.count('@') == 1, 'Only one @ is allowed in include path'
            self.path, self.subpath = self.path.split('@', 1)


def resolve_includes(conf_obj, base_path=None):
    if dict_like(conf_obj):
        return {k: resolve_includes(v, base_path) for k, v in conf_obj.items()}
    if isinstance(conf_obj, list):
        return [resolve_includes(v, base_path) for v in conf_obj]
    if hasattr(conf_obj, 'tag') and conf_obj.tag == 'dracon_include':
        return load_yaml(load_raw_conf_str(conf_obj.value))
    return conf_obj


##────────────────────────────────────────────────────────────────────────────}}}
## {{{                    --     yaml load & compose     --
from ruamel.yaml import YAML
from ruamel.yaml.composer import Composer
from ruamel.yaml.nodes import ScalarNode
from ruamel.yaml.events import (
    AliasEvent,
    ScalarEvent,
)


class DraconComposer(Composer):

    def compose_node(self, parent, index):
        event = self.parser.peek_event()

        if self.parser.check_event(ScalarEvent):
            if event.style is None and MergeKey.is_merge_key(event.value):
                event.tag = 'dracon_merge'  # Tag merge key as such (if unquoted)
            return super().compose_node(parent, index)

        if self.parser.check_event(AliasEvent):
            event = self.parser.get_event()
            alias = event.anchor
            if alias in self.anchors:
                # a regular alias that we found in the current document
                return self.return_alias(self.anchors[alias])
            else:
                # we'll need to attempt resolving the alias later,
                # it might be a pkg or file include
                return ScalarNode(
                    tag='dracon_include',
                    value=event.anchor,
                    start_mark=event.start_mark,
                    end_mark=event.end_mark,
                )

        return super().compose_node(parent, index)


def perform_merges(conf_obj):

    if isinstance(conf_obj, list):
        return [perform_merges(v) for v in conf_obj]

    if dict_like(conf_obj):
        res = {}
        for key, value in conf_obj.items():
            if hasattr(key, 'tag') and key.tag == 'dracon_merge':
                print(f'Merging detected with key {key.value}')
                merge_key = MergeKey(raw=key.value)
                # res[key.value] = perform_merges(updated_dict(res.get(key.value), value))
                res[key.value] = perform_merges(value)
            else:
                res[key] = perform_merges(value)
        return res

    return conf_obj


def dracon_post_process(loaded):
    loaded = resolve_includes(loaded)
    loaded = perform_merges(loaded)
    return loaded


def load_yaml(content: str):
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.Composer = DraconComposer
    loaded_raw = yaml.load(content)
    return dracon_post_process(loaded_raw)


content = load_raw_conf_str('pkg:dracon:tests/configs/base.yaml')
loaded = load_yaml(content)
loaded


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                       --     test mergekey     --
import pytest
from enum import Enum
from typing import Optional
from pydantic import BaseModel, ValidationError


def test_merge_key_initialization():
    mk = MergeKey(raw="<<{+<}")
    assert mk.dict_mode == MergeMode.APPEND
    assert mk.dict_priority == MergePriority.NEW
    assert mk.list_mode == MergeMode.REPLACE
    assert mk.list_priority == MergePriority.EXISTING


def test_merge_key_is_merge_key():
    assert MergeKey.is_merge_key("<<{+<}")
    assert MergeKey.is_merge_key("<<[+]{<}")
    assert not MergeKey.is_merge_key("normal_key")


def test_merge_key_dict_mode_and_priority():
    mk = MergeKey(raw="<<{+<}")
    assert mk.dict_mode == MergeMode.APPEND
    assert mk.dict_priority == MergePriority.NEW

    mk = MergeKey(raw="<<{~>}")
    assert mk.dict_mode == MergeMode.REPLACE
    assert mk.dict_priority == MergePriority.EXISTING


def test_merge_key_list_mode_and_priority():
    mk = MergeKey(raw="<<[+<]")
    assert mk.list_mode == MergeMode.APPEND
    assert mk.list_priority == MergePriority.NEW

    mk = MergeKey(raw="<<[~>]")
    assert mk.list_mode == MergeMode.REPLACE
    assert mk.list_priority == MergePriority.EXISTING


def test_merge_key_depth():
    mk = MergeKey(raw="<<{+2<}")
    assert mk.dict_depth == 2
    assert mk.list_depth is None

    mk = MergeKey(raw="<<[+3]{+2<}")
    assert mk.dict_depth == 2
    assert mk.list_depth == 3


def test_merge_key_combined_options():
    mk = MergeKey(raw="<<[+<]{~>}")
    assert mk.dict_mode == MergeMode.REPLACE
    assert mk.dict_priority == MergePriority.EXISTING
    assert mk.list_mode == MergeMode.APPEND
    assert mk.list_priority == MergePriority.NEW


def test_merge_key_invalid_combinations():
    with pytest.raises(ValidationError):
        MergeKey(raw="<<{+~}")

    with pytest.raises(ValidationError):
        MergeKey(raw="<<{<>}")


@pytest.mark.parametrize(
    "raw,expected_dict_mode,expected_dict_priority,expected_list_mode,expected_list_priority",
    [
        ("<<{+<}", MergeMode.APPEND, MergePriority.NEW, MergeMode.REPLACE, MergePriority.EXISTING),
        (
            "<<[~]{>}",
            MergeMode.APPEND,
            MergePriority.EXISTING,
            MergeMode.REPLACE,
            MergePriority.EXISTING,
        ),
        (
            "<<[+]{~<}",
            MergeMode.REPLACE,
            MergePriority.NEW,
            MergeMode.APPEND,
            MergePriority.EXISTING,
        ),
        ("<<", MergeMode.APPEND, MergePriority.EXISTING, MergeMode.REPLACE, MergePriority.EXISTING),
    ],
)
def test_merge_key_various_combinations(
    raw, expected_dict_mode, expected_dict_priority, expected_list_mode, expected_list_priority
):
    mk = MergeKey(raw=raw)
    assert mk.dict_mode == expected_dict_mode
    assert mk.dict_priority == expected_dict_priority
    assert mk.list_mode == expected_list_mode
    assert mk.list_priority == expected_list_priority


# Additional tests for edge cases and specific scenarios


def test_merge_key_empty_options():
    mk = MergeKey(raw="<<")
    assert mk.dict_mode == MergeMode.APPEND
    assert mk.dict_priority == MergePriority.EXISTING
    assert mk.list_mode == MergeMode.REPLACE
    assert mk.list_priority == MergePriority.EXISTING


def test_merge_key_only_dict_options():
    mk = MergeKey(raw="<<{+<}")
    assert mk.dict_mode == MergeMode.APPEND
    assert mk.dict_priority == MergePriority.NEW
    assert mk.list_mode == MergeMode.REPLACE
    assert mk.list_priority == MergePriority.EXISTING


def test_merge_key_only_list_options():
    mk = MergeKey(raw="<<[~>]")
    assert mk.dict_mode == MergeMode.APPEND
    assert mk.dict_priority == MergePriority.EXISTING
    assert mk.list_mode == MergeMode.REPLACE
    assert mk.list_priority == MergePriority.EXISTING


def test_merge_key_multiple_depth_specifications():
    mk = MergeKey(raw="<<[+2]{+3<}")
    assert mk.dict_depth == 3
    assert mk.list_depth == 2


def test_merge_key_ignore_invalid_depth():
    mk = MergeKey(raw="<<{+invalid<}")
    assert mk.dict_depth is None
    assert mk.dict_mode == MergeMode.APPEND
    assert mk.dict_priority == MergePriority.NEW


##────────────────────────────────────────────────────────────────────────────}}}
from copy import deepcopy
from typing import Any, Dict, List


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


## {{{                        --     test merge     --


import pytest


def test_basic_merge():

    d1 = {"a": 1, "b": 2}
    d2 = {"b": 3, "c": 4}
    mk = MergeKey(raw="<<{>}")
    result = merged(d1, d2, mk)
    assert result == {"a": 1, "b": 2, "c": 4}


def test_merge_with_new_priority():
    d1 = {"a": 1, "b": 2}
    d2 = {"b": 3, "c": 4}
    mk = MergeKey(raw="<<{<}")
    result = merged(d1, d2, mk)
    assert result == {"a": 1, "b": 3, "c": 4}


def test_merge_nested_dicts():
    d1 = {"a": 1, "b": {"x": 10, "y": 20}}
    d2 = {"b": {"y": 30, "z": 40}, "c": 5}
    mk = MergeKey(raw="<<{+>}")
    result = merged(d1, d2, mk)
    assert result == {"a": 1, "b": {"x": 10, "y": 20, "z": 40}, "c": 5}


def test_merge_replace_mode():
    d1 = {"a": 1, "b": {"x": 10, "y": 20}}
    d2 = {"b": {"z": 30}, "c": 5}
    mk = MergeKey(raw="<<{~>}")
    result = merged(d1, d2, mk)
    assert result == {"a": 1, "b": {"x": 10, "y": 20}, "c": 5}



def test_merge_lists_append_mode():
    d1 = {"a": [1, 2], "b": 3}
    d2 = {"a": [3, 4], "c": 5}
    mk = MergeKey(raw="<<[+]{>}")
    result = merged(d1, d2, mk)
    assert result == {"a": [1, 2, 3, 4], "b": 3, "c": 5}


def test_merge_lists_replace_mode():
    d1 = {"a": [1, 2], "b": 3}
    d2 = {"a": [3, 4], "c": 5}
    mk = MergeKey(raw="<<[~]{>}")
    result = merged(d1, d2, mk)
    assert result == {"a": [1, 2], "b": 3, "c": 5}


def test_merge_lists_with_priority():
    d1 = {"a": [1, 2], "b": 3}
    d2 = {"a": [3, 4], "c": 5}
    mk = MergeKey(raw="<<[~<]{>}")
    result = merged(d1, d2, mk)
    assert result == {"a": [3, 4], "b": 3, "c": 5}


def test_merge_mixed_types():
    d1 = {"a": [1, 2], "b": {"x": 10}}
    d2 = {"a": 3, "b": [4, 5]}
    mk = MergeKey(raw="<<[+]{+<}")
    result = merged(d1, d2, mk)
    assert result == {"a": 3, "b": [4, 5]}


def test_merge_with_none_values():
    d1 = {"a": 1, "b": None}
    d2 = {"b": 2, "c": None}
    mk = MergeKey(raw="<<{>}")
    result = merged(d1, d2, mk)
    assert result == {"a": 1, "b": None, "c": None}


def test_merge_empty_dicts():
    d1 = {}
    d2 = {"a": 1}
    mk = MergeKey(raw="<<{>}")
    result = merged(d1, d2, mk)
    assert result == {"a": 1}


def test_merge_identical_dicts():
    d1 = {"a": 1, "b": 2}
    d2 = {"a": 1, "b": 2}
    mk = MergeKey(raw="<<{>}")
    result = merged(d1, d2, mk)
    assert result == {"a": 1, "b": 2}


def test_merge_nested_lists():
    d1 = {"a": [1, [2, 3]], "b": 4}
    d2 = {"a": [5, [6, 7]], "c": 8}
    mk = MergeKey(raw="<<[+]{>}")
    result = merged(d1, d2, mk)
    assert result == {"a": [1, [2, 3], 5, [6, 7]], "b": 4, "c": 8}


def test_merge_nested_dicts_with_lists():
    d1 = {"a": {"x": [1, 2]}, "b": 3}
    d2 = {"a": {"x": [3, 4], "y": 5}, "c": 6}
    mk = MergeKey(raw="<<[+]{+<}")
    result = merged(d1, d2, mk)
    assert result == {"a": {"x": [1, 2, 3, 4], "y": 5}, "b": 3, "c": 6}

@pytest.mark.parametrize(
    "raw,d1,d2,expected",
    [
        ("<<{+}", {"a": 1}, {"b": 2}, {"a": 1, "b": 2}),
        ("<<{+<}", {"a": 1, "b": 2}, {"b": 3, "c":4}, {"a": 1, "b": 3, "c": 4}),
        ("<<{+>}", {"a": 1, "b": 2}, {"b": 3, "c":4}, {"a": 1, "b": 2, "c": 4}),

        ("<<[~<]", {"a": [1, 2]}, {"a": [3, 4]}, {"a": [3, 4]}),
        ("<<[~>]", {"a": [1, 2]}, {"a": [3, 4]}, {"a": [1, 2]}),

        ("<<[+>]", {"a": [1, 2]}, {"a": [3, 4]}, {"a": [1, 2, 3, 4]}),
        ("<<[+<]", {"a": [1, 2]}, {"a": [3, 4]}, {"a": [3, 4, 1, 2]}),


        ("<<{+4>}", {"a": {"b": {"c": 1}}}, {"a": {"b": {"d": 2}}}, {"a": {"b": {"c": 1, "d": 2}}}),
        ("<<{+3>}", {"a": {"b": {"c": 1}}}, {"a": {"b": {"d": 2}}}, {"a": {"b": {"c": 1}}}),

        (
            "<<{<}",
            {"a": 1, "b": 2, "c": 3},
            {"a": 4, "b": 5, "d": 6},
            {"a": 4, "b": 5, "c": 3, "d": 6},
        ),
        (
            "<<[+]{+<}",
            {"a": [{"x": 1}, {"y": 2}], "b": 3},
            {"a": [{"x": 4}, {"z": 5}], "c": 6},
            {"a": [{"x": 1}, {"y": 2}, {"x": 4}, {"z": 5}], "b": 3, "c": 6},
        ),
        (
            "<<[+>]{3+<}",
            {"a": [1, {"b": [2, 3]}, 4], "c": {"d": {"e": 5}}, "f": 6, 'i': 0},
            {"a": [7, {"b": [8, 9]}, 10], "c": {"d": {"g": 11}}, "h": 12, 'i' :'hi'},
            {
                "a": [1, {"b": [2, 3]}, 4, 7, {"b": [8, 9]}, 10],
                "c": {"d": {"g": 11}},
                "f": 6,
                "h": 12,
                'i': 'hi',
            },
        ),

        (
            "<<[+>]{+<}",
            {"a": 1, "b": {"x": 10, "y": [1, 2]}},
            {"b": {"y": [3, 4], "z": 20, "x": 'yo'}, "c": 3},
            {"a": 1, "b": {"x": 'yo', "y": [1, 2, 3, 4], "z": 20}, "c": 3},
        ),
        (
            "<<[+]{+<}",
            {"a": {"x": [1, 2]}, "b": 3},
            {"a": {"x": [3, 4], "y": 5}, "c": 6},
            {"a": {"x": [1, 2, 3, 4], "y": 5}, "b": 3, "c": 6},
        ),
        (
            "<<[+]{>}",
            {"a": [1, [2, 3]], "b": 4},
            {"a": [5, [6, 7]], "c": 8},
            {"a": [1, [2, 3], 5, [6, 7]], "b": 4, "c": 8},
        ),
    ],
)
def test_merge_with_various_options(raw, d1, d2, expected):
    mk = MergeKey(raw=raw)
    result = merged(d1, d2, mk)
    assert result == expected


##────────────────────────────────────────────────────────────────────────────}}}
