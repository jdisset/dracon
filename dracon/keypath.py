# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

from enum import Enum
from functools import lru_cache
from typing import List, Union, Hashable, Any, Optional, TypeVar, Type, Protocol, Tuple, Deque
from typing_extensions import runtime_checkable
from collections import deque
from ruamel.yaml.nodes import Node
from dracon.utils import node_repr, list_like, dict_like
import re

import logging

logger = logging.getLogger(__name__)


class KeyPathToken(Enum):
    ROOT = 0
    UP = 1
    MAPPING_KEY = 2  # indicates that the path points to the key of a mapping, not the value
    SINGLE_WILDCARD = 3  # represents '*' in glob patterns
    MULTI_WILDCARD = 4  # represents '**' in glob patterns


MAPPING_KEY = KeyPathToken.MAPPING_KEY


@lru_cache(maxsize=512)
def escape_keypath_part(part: str) -> str:
    return part.replace('.', '\\.').replace('/', '\\/')


@lru_cache(maxsize=512)
def unescape_keypath_part(part: str) -> str:
    return part.replace('\\.', '.').replace('\\/', '/')


def parse_part(part: str) -> Union[Hashable, KeyPathToken]:
    if part == '*':
        return KeyPathToken.SINGLE_WILDCARD
    elif part == '**':
        return KeyPathToken.MULTI_WILDCARD
    return part


@lru_cache(maxsize=1000)
def simplify_parts_recursive(
    parts: Tuple[Union[Hashable, KeyPathToken], ...],
) -> Tuple[Union[Hashable, KeyPathToken], ...]:
    if not parts:
        return tuple()

    if len(parts) == 1:
        return parts

    if parts[-1] == KeyPathToken.ROOT:
        return (KeyPathToken.ROOT,)

    if parts[-1] == KeyPathToken.UP:
        # Simplify everything before the UP token
        prefix = simplify_parts_recursive(parts[:-1])

        if not prefix:
            # If nothing before UP, keep the UP
            return (KeyPathToken.UP,)

        if prefix[-1] == KeyPathToken.ROOT:
            # Can't go up from root
            return prefix

        if prefix[-1] == KeyPathToken.UP:
            # Multiple UPs stack
            return prefix + (KeyPathToken.UP,)

        # Remove the last element unless it's ROOT
        if len(prefix) > 1 and prefix[-2] == KeyPathToken.MAPPING_KEY:
            # If we're removing a mapping key, remove both tokens
            return prefix[:-2]
        return prefix[:-1]

    # Simplify everything before current token and append current
    return simplify_parts_recursive(parts[:-1]) + (parts[-1],)


# def simplify_parts(parts: Union[List, Tuple]) -> Tuple[Union[Hashable, KeyPathToken], ...]:
# return simplify_parts_recursive(tuple(parts))


@lru_cache(maxsize=10000)
def simplify_parts_cached(parts: Tuple) -> Tuple[Union[Hashable, KeyPathToken], ...]:
    """
    Non-recursive version of simplify_parts that processes parts from left to right using a stack.
    This version maintains the same logic but eliminates recursion for better performance with deep paths.
    """
    if not parts:
        return tuple()

    # Convert input to tuple if it's a list
    parts = tuple(parts)

    # Special cases for simple inputs
    if len(parts) == 1:
        return parts

    # Initialize stack for processing
    stack: Deque[Union[Hashable, KeyPathToken]] = deque()

    for part in parts:
        if part == KeyPathToken.ROOT:
            # ROOT token clears the stack and becomes the only element
            stack.clear()
            stack.append(KeyPathToken.ROOT)

        elif part == KeyPathToken.UP:
            if not stack:
                # If stack is empty, just add UP token
                stack.append(KeyPathToken.UP)
            elif stack[-1] == KeyPathToken.ROOT:
                # Can't go up from root, keep the root
                continue
            elif stack[-1] == KeyPathToken.UP:
                # Multiple UPs stack
                stack.append(KeyPathToken.UP)
            else:
                # Remove the last element unless it's ROOT
                if len(stack) >= 2 and stack[-2] == KeyPathToken.MAPPING_KEY:
                    # If we're removing a mapping key, remove both tokens
                    stack.pop()
                    stack.pop()
                else:
                    stack.pop()

        else:
            # For any other token, just append it to the stack
            stack.append(part)

    return tuple(stack)


def simplify_parts(parts):
    if not parts:
        return tuple()
    return simplify_parts_cached(tuple(parts))


@lru_cache(maxsize=512)
def parse_string(path: str) -> List[Union[Hashable, KeyPathToken]]:
    if not path:
        return []

    parts = []
    dot_count = 0
    current_part = ""

    escaped = False

    for char in path:
        if char == '\\' and not escaped:
            escaped = True
            continue
        elif char == '/' and not escaped:
            if current_part:
                parts.append(parse_part(current_part))
                current_part = ""
            parts.append(KeyPathToken.ROOT)
            dot_count = 0
        elif char == '.' and not escaped:
            if current_part:
                parts.append(parse_part(current_part))
                current_part = ""
            dot_count += 1
            if dot_count > 1:
                parts.append(KeyPathToken.UP)
        else:
            current_part += char
            dot_count = 0
        escaped = False
    if current_part:
        parts.append(parse_part(current_part))
    return parts


class KeyPath:
    def __init__(
        self, path: Union[str, List[Union[Hashable, KeyPathToken]]], simplify: bool = True
    ):
        self.is_simple = False
        if isinstance(path, (list, tuple)) and not isinstance(path, str):
            self.parts = list(path)  # Create a copy to avoid modifying the input
        else:
            self.parts = self._parse_string(str(path))
        if simplify:
            self.simplify()

    def _parse_string(self, path: str) -> List[Union[Hashable, KeyPathToken]]:
        return parse_string(path)

    def clear(self) -> 'KeyPath':
        self.parts = []
        return self

    def rootless(self) -> 'KeyPath':
        simple = self.simplified()
        if simple.parts[0] == KeyPathToken.ROOT:
            simple.parts = simple.parts[1:]
        return simple

    def up(self, simplify=True) -> 'KeyPath':
        self.is_simple = False
        self.parts.append(KeyPathToken.UP)
        if simplify:
            return self.simplify()
        return self

    # unicode emoji for key:
    @property
    def parent(self) -> 'KeyPath':
        return self.copy().up()

    def pop(self) -> Union[Hashable, KeyPathToken]:
        return self.parts.pop()

    def front_pop(self) -> Union[Hashable, KeyPathToken]:
        return self.parts.pop(0)

    def with_added_parts(self, *parts) -> 'KeyPath':
        kcopy = self.copy()
        kcopy.parts.extend(parts)
        return kcopy

    def down(self, path: "str | KeyPath | KeyPathToken") -> 'KeyPath':
        self.is_simple = False
        if isinstance(path, int):
            path = str(path)
        if isinstance(path, KeyPathToken):
            self.parts.append(path)
        elif isinstance(path, KeyPath):
            self.parts.extend(path.parts)
        elif isinstance(path, list):
            return self.down(KeyPath(path))
        else:
            # escape if it's a string
            return self.down(KeyPath(escape_keypath_part(path)))
        return self

    def match(self, target: 'KeyPath') -> bool:
        """
        Match this KeyPath (as a pattern) against a target KeyPath.
        Supports '*' for single-level wildcard, '**' for multi-level wildcard,
        and partial matching within individual path segments.
        """

        def match_parts(pattern_parts, target_parts):
            pi = ti = 0
            while pi < len(pattern_parts) and ti < len(target_parts):
                if pattern_parts[pi] == KeyPathToken.MULTI_WILDCARD:
                    # Try to match the rest of the pattern against the rest of the target
                    return any(
                        match_parts(pattern_parts[pi + 1 :], target_parts[i:])
                        for i in range(ti, len(target_parts) + 1)
                    )
                elif pattern_parts[pi] == KeyPathToken.SINGLE_WILDCARD:
                    # Match any single part
                    pi += 1
                    ti += 1
                elif isinstance(pattern_parts[pi], str) and isinstance(target_parts[ti], str):
                    # Convert glob pattern to regex pattern
                    regex_pattern = '^' + re.escape(pattern_parts[pi]).replace('\\*', '.*') + '$'
                    if re.match(regex_pattern, target_parts[ti]):
                        pi += 1
                        ti += 1
                    else:
                        return False
                elif pattern_parts[pi] == target_parts[ti]:
                    # Exact match for non-string parts (e.g., KeyPathToken.ROOT)
                    pi += 1
                    ti += 1
                else:
                    return False
            # Check if we've matched all parts
            return pi == len(pattern_parts) and ti == len(target_parts)

        return match_parts(self.simplified().parts, target.simplified().parts)

    # same as down
    def append(self, part: Union[Hashable, KeyPathToken]) -> 'KeyPath':
        return self.down(part)

    @property
    def stem(self):
        if self.is_mapping_key():
            return self.parts[:-2]
        if len(self.parts) <= 1:
            return '/'
        return self.parts[-1]

    # same as down but not in place
    def __add__(self, other) -> 'KeyPath':
        return self.copy().down(other)

    def copy(self) -> 'KeyPath':
        kc = KeyPath([], simplify=False)
        kc.parts = self.parts.copy()
        kc.is_simple = self.is_simple
        return kc

    def __deepcopy__(self, memo) -> 'KeyPath':
        return self.copy()

    def simplify(self) -> 'KeyPath':
        if self.is_simple:
            return self
        self.parts = list(simplify_parts(self.parts))
        self.is_simple = True
        return self

    def simplified(self) -> 'KeyPath':
        if self.is_simple:
            return self.copy()
        new = KeyPath(self.parts, simplify=True)
        return new

    def __str__(self) -> str:
        result = ''
        prev = None
        for part in self.parts:
            if part == KeyPathToken.ROOT:
                result += '/'
            elif part == KeyPathToken.UP:
                result += '.' if prev == KeyPathToken.UP else '..'
            elif part == MAPPING_KEY:
                result += '🔑:' if prev in {KeyPathToken.ROOT, KeyPathToken.UP, None} else '.🔑:'
            elif part == KeyPathToken.SINGLE_WILDCARD:
                result += '*' if prev in {KeyPathToken.ROOT, KeyPathToken.UP, None} else '.*'
            elif part == KeyPathToken.MULTI_WILDCARD:
                result += '**' if prev in {KeyPathToken.ROOT, KeyPathToken.UP, None} else '.**'
            else:
                if prev not in {KeyPathToken.ROOT, KeyPathToken.UP, None, MAPPING_KEY}:
                    result += '.'
                result += escape_keypath_part(str(part))
            prev = part
        return result

    def __repr__(self) -> str:
        return f"KeyPath('{self}')"

    def __len__(self) -> int:
        if self.is_mapping_key():
            return len(self.parts) - 1
        return len(self.parts)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, KeyPath):
            return NotImplemented
        return self.parts == other.parts

    def __hash__(self) -> int:
        return hash(tuple(self.parts))

    def __getitem__(self, index) -> Union[Hashable, KeyPathToken]:
        return self.parts[index]

    def __iter__(self):
        return iter(self.parts)

    def startswith(self, other: 'KeyPath') -> bool:
        if len(other) > len(self):
            return False
        return self.parts[: len(other)] == other.parts

    def check_correctness(self) -> None:
        if self.parts and self.parts[-1] == KeyPathToken.MAPPING_KEY:
            raise ValueError(f'KeyPath cannot end with a mapping key: {self}')

    # protocol that tests if an object has a keypath_passthrough prperty:
    @runtime_checkable
    class Passthrough(Protocol):
        @property
        def keypath_passthrough(self):
            raise NotImplementedError

    def get_obj(
        self, obj: Any, create_path_if_not_exists=False, default_mapping_constructor=None
    ) -> Any:
        if not self.is_simple:
            simplified = self.simplified()
            return simplified.get_obj(obj, create_path_if_not_exists, default_mapping_constructor)

        self.check_correctness()

        # make sure there's no wildcards in the path
        if any(
            part in {KeyPathToken.SINGLE_WILDCARD, KeyPathToken.MULTI_WILDCARD}
            for part in self.parts
        ):
            raise ValueError(f'Cannot get object from path with wildcards: {self}')

        res = obj
        try:
            for i, part in enumerate(self.parts):
                if part == KeyPathToken.UP:
                    raise ValueError(f'Cannot get object from unsimplifiable path: {self}')
                if part == KeyPathToken.ROOT:
                    continue
                if part == KeyPathToken.MAPPING_KEY:
                    if i != len(self.parts) - 2:
                        raise ValueError(f'Invalid mapping key in path: {self}')
                    assert hasattr(res, 'get_key')
                    res = res.get_key(self.parts[-1])
                    return res
                res = _get_obj_impl(
                    res, part, create_path_if_not_exists, default_mapping_constructor
                )
        except AttributeError as e:
            raise AttributeError(f'Could not get object from path: {self}') from e
        return res

    def is_mapping_key(self, simplify=False) -> bool:
        if simplify and not self.is_simple:
            simplified = self.simplified()
            return simplified.is_mapping_key(simplify=False)
        if len(self.parts) < 2:
            return False
        return self.parts[-2] == KeyPathToken.MAPPING_KEY

    def removed_mapping_key(self) -> 'KeyPath':
        if not self.is_mapping_key():
            return self
        kcopy = self.copy()
        kcopy.parts.pop(-2)
        return kcopy


def _get_obj_impl(
    obj: Any, attr: Any, create_path_if_not_exists=False, default_mapping_constructor=None
) -> Any:
    """
    Get an attribute from an object, handling various types of objects.
    """
    from dracon.deferred import DeferredNode

    if isinstance(obj, DeferredNode):
        return _get_obj_impl(
            obj.keypath_passthrough,
            attr,
            create_path_if_not_exists,
            default_mapping_constructor,
        )
    if list_like(obj):
        return obj[int(attr)]
    try:
        return obj[attr]
    except (TypeError, KeyError):
        if hasattr(obj, attr):
            return getattr(obj, attr)
        else:
            try:  # check if we can access it with __getitem__
                return obj[attr]
            except (TypeError, KeyError) as e:
                if create_path_if_not_exists:
                    logging.debug(f'Creating path {attr} in {obj} of type {type(obj)}')
                    assert default_mapping_constructor is not None
                    obj[attr] = default_mapping_constructor()
                    return obj[attr]
                if isinstance(obj, Node):
                    import traceback

                    tback = traceback.format_exc(limit=10)

                    raise AttributeError(
                        f'Could not find attribute {attr} in node \n{node_repr(obj)} of type {type(obj)}. {create_path_if_not_exists=}, {default_mapping_constructor=}. \nTraceback:\n{tback}'
                    ) from None
                else:
                    raise AttributeError(f'Could not find attribute {attr} in {obj}') from None


ROOTPATH = KeyPath('/')
