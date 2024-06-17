import os
import yaml
from pathlib import Path
from yaml.constructor import ConstructorError
import os
import yaml
import re
from rich import print as rprint
from pydantic import BaseModel
from typing import List
from collections import namedtuple
from enum import Enum
from typing import List, Dict, Any, Union, Optional
from pathlib import Path
import xxhash
import base64


def get_hash(data: str) -> str:
    hash_value = xxhash.xxh128(data).digest()
    return base64.b32encode(hash_value).decode('utf-8').rstrip('=')


CONFIG_FILE = './test_0.yaml'
cfile = open(CONFIG_FILE, 'r').read()
loaded = yaml.safe_load(cfile)

## {{{                           --     utils     --


def list_like(obj: Any) -> bool:
    return isinstance(obj, (list, tuple, set))


def obj_get(obj: Any, attr: str):
    """
    Get an attribute from an object, handling various types of objects.
    """
    if list_like(obj):
        return obj[int(attr)]
    if hasattr(obj, attr):
        return getattr(obj, attr)
    else:
        try:  # check if we can access it with __getitem__
            return obj[attr]
        except (TypeError, KeyError):
            raise AttributeError(f'Could not find attribute {attr} in {obj}')


def obj_resolver(obj: Any, attr_path: str):
    res = obj
    for attr in attr_path.split('.'):
        try:
            res = obj_get(res, attr)
        except (AttributeError, KeyError, IndexError) as e:
            raise AttributeError(f'Could not resolve {attr_path} in {type(obj)} instance: {e}')
    return res


##────────────────────────────────────────────────────────────────────────────}}}


## {{{                          --     loaders     --
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


DEFAULT_ESCAPE_KEYS = ['<<']


def load_raw_conf(path: str, escape_keys=None) -> str:
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


class IncludeMatch(BaseModel):
    path: str
    start: int
    end: int
    name: Optional[str] = None
    subpath: Optional[str] = None

    def model_post_init(self, *args, **kwargs):
        super().model_post_init(*args, **kwargs)
        if '@' in self.path:
            assert self.path.count('@') == 1, 'Only one @ is allowed in include path'
            self.path, self.subpath = self.path.split('@', 1)


def collect_includes(content, include_markers=':/') -> List[IncludeMatch]:
    include_pattern = re.compile(r'(?<!["\'])\*([a-zA-Z0-9_@/:\-\.]+)')
    return [
        IncludeMatch(path=match.group(1), start=match.start() + 1, end=match.end())
        for match in include_pattern.finditer(content)
        if any([c in match.group(1) for c in include_markers])
    ]


def with_indent(content: str, indent: int) -> str:
    return '\n'.join([f'{" " * indent}{line}' for line in content.split('\n')])


def make_anchor_str(anchors: Dict[str, str]):
    def single(i, alias, raw):
        return f'{i}: &{alias}\n{with_indent(raw, 2)}'

    all_anchors = '\n'.join(
        [single(i, alias, raw) for i, (alias, raw) in enumerate(anchors.items())]
    )
    final = ''
    if all_anchors:
        final = f'__dracon__anchors:\n{with_indent(all_anchors, 2)}'
    return final

def load_conf(path: str) -> str:
    raw = load_raw_conf(path)
    include_matches = collect_includes(raw)
    offset = 0
    anchors = {}

    for include in include_matches:
        inner_raw = load_conf(include.path)
        if include.subpath:
            loaded = yaml.safe_load(inner_raw)
            inner_loaded = obj_resolver(loaded, include.subpath)
            inner_raw = yaml.dump(inner_loaded)

        alias = '__dracon__' + get_hash(inner_raw + include.path)
        anchors[alias] = inner_raw

        raw = raw[: include.start + offset] + alias + raw[include.end + offset :]
        offset += len(alias) - (include.end - include.start)

    final_raw = make_anchor_str(anchors) + f'\n{raw}'

    loaded = yaml.safe_load(final_raw)
    if '__dracon__anchors' in loaded:
        del loaded['__dracon__anchors']

    return yaml.dump(loaded)




##────────────────────────────────────────────────────────────────────────────}}}



# create Enum for dict_modes:
# - merge
# - replace


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
    list_mode: MergeMode = MergeMode.REPLACE
    list_priority: MergePriority = MergePriority.EXISTING

    @staticmethod
    def is_merge_key(key: str) -> bool:
        return key.startswith('<<')

    @staticmethod
    def get_mode_priority(mode_str: str) -> tuple[Optional[MergeMode], Optional[MergePriority]]:
        # + means RECURSE or APPEND
        # ~ means REPLACE
        # > means EXISTING
        # < means NEW
        mode, priority = None, None
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
        return mode, priority

    def model_post_init(self, *args, **kwargs):
        # to find the dict_mode and list_mode, we need to parse the raw key
        # things inside {} concern the dict_mode and priority
        # things inside [] concern the list_mode and priority

        dict_str = re.search(r'{(.+)}', self.raw)

        if dict_str:
            dict_str = dict_str.group(1)
            m, p = self.get_mode_priority(dict_str)
            if m:
                self.dict_mode = m
            if p:
                self.dict_priority = p

        list_str = re.search(r'\[(.+)\]', self.raw)
        if list_str:
            list_str = list_str.group(1)
            m, p = self.get_mode_priority(list_str)
            if m:
                self.list_mode = m
            if p:
                self.list_priority = p




composed = load_conf('pkg:dracon:tests/test_1.yaml')
# timeit:
from timeit import timeit

print(timeit(lambda: load_conf('pkg:dracon:tests/test_1.yaml'), number=10))


# composed = compose_full_raw_conf('pkg:dracon:tests/test_1.yaml')

print(composed)

##


content = load_raw_conf('pkg:dracon:tests/configs/simple.yaml')
print(content)
loaded = yaml.safe_load(content)
print(loaded['config'])


## {{{                          --     archive     --


def load_conf_old(path: str) -> str:
    raw = load_raw_conf(path)
    include_matches = collect_includes(raw)
    offset = 0
    anchors = {}

    for include in include_matches:
        inner_raw = load_conf(include.path)
        if include.subpath:
            loaded = yaml.safe_load(inner_raw)
            print(f'{include.path} -> {include.subpath} -> {loaded}')
            inner_loaded = obj_resolver(loaded, include.subpath)
            inner_raw = yaml.dump(inner_loaded)

        alias = '__dracon__' + get_hash(inner_raw + include.path)
        anchors[alias] = inner_raw

        raw = raw[: include.start + offset] + alias + raw[include.end + offset :]
        offset += len(alias) - (include.end - include.start)

    final_raw = make_anchor_str(anchors) + f'\n{raw}'

    loaded = yaml.safe_load(final_raw)
    if '__dracon__anchors' in loaded:
        del loaded['__dracon__anchors']

    return yaml.dump(loaded)


def compose_full_raw_conf(path: str) -> str:
    def __impl(path: str) -> tuple[str, List[tuple[str, str]]]:
        raw = load_raw_conf(path)
        include_matches = collect_includes(raw)
        offset = 0
        anchors = {}

        for include in include_matches:
            inner_raw, inner_anchors = __impl(include.path)
            alias = '__dracon__' + get_hash(inner_raw + include.path + str(inner_anchors))
            raw = raw[: include.start + offset] + alias + raw[include.end + offset :]
            offset += len(alias) - (include.end - include.start)
            anchors.update(inner_anchors)
            anchors[alias] = inner_raw

        return raw, anchors

    composed, anchors = __impl(path)

    def make_anchor_str(i, alias, raw):
        return f'{i}: &{alias}\n{with_indent(raw, 2)}'

    all_anchors = '\n'.join(
        [make_anchor_str(i, alias, raw) for i, (alias, raw) in enumerate(anchors.items())]
    )

    final = f'__dracon__anchors:\n{with_indent(all_anchors, 2)}\n{composed}'

    return final


composed = compose_full_raw_conf('pkg:dracon:tests/test_1.yaml')

print(composed)


##────────────────────────────────────────────────────────────────────────────}}}o
