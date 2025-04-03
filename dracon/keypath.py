from enum import Enum
from functools import lru_cache
from typing import List, Union, Hashable, Any, Protocol
from typing_extensions import runtime_checkable
from collections import deque
import re


class KeyPathToken(Enum):
    ROOT = 0
    UP = 1
    MAPPING_KEY = 2
    SINGLE_WILDCARD = 3
    MULTI_WILDCARD = 4

    def __repr__(self):
        return f'<{self.name}>'


@lru_cache(maxsize=512)
def escape_keypath_part(part: str) -> str:
    return part.replace('\\', '\\\\').replace('/', '\\/')


@lru_cache(maxsize=512)
def unescape_keypath_part(part: str) -> str:
    return part.replace('\\/', '/').replace('\\\\', '\\')


def parse_part(part: str) -> Union[Hashable, KeyPathToken, None]:
    tokens = {
        '*': KeyPathToken.SINGLE_WILDCARD,
        '**': KeyPathToken.MULTI_WILDCARD,
        '..': KeyPathToken.UP,
        '.': None,
    }
    return tokens.get(part, unescape_keypath_part(part))


@lru_cache(maxsize=1000)
def parse_string(path: str) -> List[Union[Hashable, KeyPathToken]]:
    if not path:
        return []
    parts: List[Union[Hashable, KeyPathToken]] = []
    is_absolute = path.startswith('/')
    if is_absolute:
        parts.append(KeyPathToken.ROOT)
        path = path[1:]
    segments = [seg for seg in re.split(r'(?<!\\)/', path) if seg]
    if not segments and path == '.':
        return []
    if not segments and path == '..':
        return (
            [KeyPathToken.UP] if not parts or parts[0] != KeyPathToken.ROOT else [KeyPathToken.ROOT]
        )
    parts.extend(p for p in map(parse_part, segments) if p is not None)
    return parts


@lru_cache(maxsize=1000)
def simplify_parts(parts_tuple):
    if not parts_tuple:
        return tuple()
    stack = deque()
    for part in parts_tuple:
        if part == KeyPathToken.ROOT:
            stack.clear()
            stack.append(KeyPathToken.ROOT)
        elif part == KeyPathToken.UP:
            if not stack or stack[-1] == KeyPathToken.ROOT:
                if not (stack and stack[-1] == KeyPathToken.ROOT):
                    stack.append(KeyPathToken.UP)
            elif stack[-1] == KeyPathToken.UP:
                stack.append(KeyPathToken.UP)
            else:
                if len(stack) >= 2 and stack[-2] == KeyPathToken.MAPPING_KEY:
                    stack.pop()
                    stack.pop()
                else:
                    stack.pop()
        elif isinstance(part, KeyPathToken):
            stack.append(part)
        else:
            stack.append(str(part))
    return tuple(stack)


class KeyPath:
    def __init__(self, path, simplify=True):
        if isinstance(path, KeyPathToken):
            input_parts = [path]
        elif isinstance(path, (list, tuple)):
            input_parts = [p if isinstance(p, KeyPathToken) else str(p) for p in path]
        else:
            input_parts = parse_string(str(path))

        if simplify:
            self.parts = list(simplify_parts(tuple(input_parts)))
            self.is_simple = True
        else:
            self.parts = input_parts
            self.is_simple = tuple(self.parts) == simplify_parts(tuple(self.parts))

    def simplify(self):
        if not self.is_simple:
            self.parts = list(simplify_parts(tuple(self.parts)))
            self.is_simple = True
        return self

    def simplified(self):
        return KeyPath(self.parts, simplify=True)

    def copy(self):
        new_kp = KeyPath([], simplify=False)
        new_kp.parts = self.parts.copy()
        new_kp.is_simple = self.is_simple
        return new_kp

    def __deepcopy__(self, memo):
        new_kp = self.copy()
        memo[id(self)] = new_kp
        return new_kp

    def down(self, path):
        self.is_simple = False

        if isinstance(path, KeyPathToken):
            new_parts = [path]
        elif isinstance(path, KeyPath):
            new_parts = path.parts
        elif isinstance(path, (list, tuple)):
            new_parts = [p if isinstance(p, KeyPathToken) else str(p) for p in path]
        else:
            new_parts = parse_string(str(path))

        self.parts.extend(new_parts)
        return self

    def up(self, simplify=True):
        self.is_simple = False
        self.parts.append(KeyPathToken.UP)
        return self.simplify() if simplify else self

    def __add__(self, other):
        if isinstance(other, KeyPathToken):
            other_parts = [other]
        elif isinstance(other, KeyPath):
            other_parts = other.parts
        elif isinstance(other, (list, tuple)):
            other_parts = [p if isinstance(p, KeyPathToken) else str(p) for p in other]
        else:
            other_parts = parse_string(str(other))

        return KeyPath(self.parts + other_parts, simplify=True)

    @property
    def parent(self):
        return self + KeyPathToken.UP

    def __eq__(self, other):
        if not isinstance(other, KeyPath):
            return NotImplemented
        return tuple(self.simplified().parts) == tuple(other.simplified().parts)

    def __hash__(self):
        return hash(tuple(self.simplified().parts))

    def __len__(self):
        return len(self.simplified().parts)

    def __str__(self):
        if not self.parts:
            return '.'

        is_absolute = self.parts and self.parts[0] == KeyPathToken.ROOT
        parts_to_join = []

        token_str = {
            KeyPathToken.UP: '..',
            KeyPathToken.SINGLE_WILDCARD: '*',
            KeyPathToken.MULTI_WILDCARD: '**',
            KeyPathToken.MAPPING_KEY: repr(KeyPathToken.MAPPING_KEY),
        }

        for part in self.parts:
            if part == KeyPathToken.ROOT:
                continue
            elif part in token_str:
                parts_to_join.append(token_str[part])
            else:
                parts_to_join.append(escape_keypath_part(str(part)))

        path_str = '/'.join(parts_to_join)

        if is_absolute:
            return "/" + path_str if parts_to_join else "/"
        else:
            return path_str if parts_to_join else "."

    def match(self, target):
        pattern_parts = self.simplified().parts
        target_parts = target.simplified().parts
        memo = {}

        def match_recursive(pi, ti):
            memo_key = (pi, ti)
            if memo_key in memo:
                return memo[memo_key]

            if pi == len(pattern_parts):
                result = ti == len(target_parts)
                memo[memo_key] = result
                return result

            pattern_part = pattern_parts[pi]

            if pattern_part == KeyPathToken.MULTI_WILDCARD:
                if match_recursive(pi + 1, ti) or (
                    ti < len(target_parts) and match_recursive(pi, ti + 1)
                ):
                    memo[memo_key] = True
                    return True
            elif ti < len(target_parts):
                target_part = target_parts[ti]
                match_found = False

                if pattern_part == KeyPathToken.SINGLE_WILDCARD:
                    match_found = True
                elif isinstance(pattern_part, str) and isinstance(target_part, str):
                    regex_pattern = '^' + re.escape(pattern_part).replace('\\*', '.*') + '$'
                    if re.match(regex_pattern, target_part):
                        match_found = True
                elif pattern_part == target_part:
                    match_found = True

                if match_found and match_recursive(pi + 1, ti + 1):
                    memo[memo_key] = True
                    return True

            memo[memo_key] = False
            return False

        return match_recursive(0, 0)

    def check_correctness(self, for_get_obj=False):
        simplified_parts = self.simplified().parts

        for i, part in enumerate(simplified_parts):
            if part == KeyPathToken.MAPPING_KEY and i < len(simplified_parts) - 2:
                raise ValueError(f'Simplified MAPPING_KEY token must be second to last: {self}')

        if for_get_obj and simplified_parts and simplified_parts[-1] == KeyPathToken.MAPPING_KEY:
            raise ValueError(f'KeyPath for get_obj cannot end with a mapping key token: {self}')

    @runtime_checkable
    class Passthrough(Protocol):
        @property
        def keypath_passthrough(self) -> Any: ...

    def get_obj(self, obj, create_path_if_not_exists=False, default_mapping_constructor=None):
        current_path = self.simplified()
        current_path.check_correctness(for_get_obj=True)

        wildcards = {KeyPathToken.SINGLE_WILDCARD, KeyPathToken.MULTI_WILDCARD}
        if any(part in wildcards for part in current_path.parts):
            raise ValueError(f'Cannot get object from path with wildcards: {self}')

        is_mapping_key_lookup = current_path.is_mapping_key()
        path_to_traverse = current_path.parts[:-2] if is_mapping_key_lookup else current_path.parts

        res = obj

        for part in path_to_traverse:
            if part == KeyPathToken.ROOT:
                res = obj
                continue
            if part == KeyPathToken.UP:
                raise ValueError(
                    f'Cannot get object from unresolvable relative path: {current_path}'
                )

            while isinstance(res, KeyPath.Passthrough):
                res = res.keypath_passthrough

            try:
                res = _get_obj_impl(
                    res, part, create_path_if_not_exists, default_mapping_constructor
                )
            except Exception as e:
                raise type(e)(
                    f"Failed to get object at path '{current_path}' resolving part '{part}': {e}"
                ) from e

        if is_mapping_key_lookup:
            key_name = current_path.parts[-1]
            if not hasattr(res, 'get_key'):
                raise TypeError(
                    f"Object at path '{KeyPath(path_to_traverse)}' does not support MAPPING_KEY lookup"
                )
            try:
                return res.get_key(key_name)
            except Exception as e:
                raise type(e)(
                    f"Failed MAPPING_KEY lookup for key '{key_name}' at path '{current_path}': {e}"
                ) from e

        return res

    def with_added_parts(self, *parts_to_add) -> 'KeyPath':
        """returns a new KeyPath with the given parts appended, simplifying the result."""
        new_kp = self.copy()
        for part in parts_to_add:
            new_kp.down(part)
        return new_kp.simplify()

    def is_mapping_key(self):
        simplified_parts = self.simplified().parts
        return len(simplified_parts) >= 2 and simplified_parts[-2] == KeyPathToken.MAPPING_KEY

    def removed_mapping_key(self):
        if not self.is_mapping_key():
            return self

        simplified_parts = self.simplified().parts
        new_parts = list(simplified_parts[:-2]) + [simplified_parts[-1]]
        result = KeyPath(new_parts, simplify=False)
        result.is_simple = True
        return result

    def __getitem__(self, index: int) -> Union[Hashable, KeyPathToken]:
        return self.parts[index]


def _get_obj_impl(obj, attr, create_path_if_not_exists=False, default_mapping_constructor=None):
    if isinstance(obj, (list, tuple)) or (
        hasattr(obj, '__getitem__')
        and hasattr(obj, '__len__')
        and not isinstance(obj, (str, bytes, dict))
    ):
        try:
            index = int(attr)
            if not (0 <= index < len(obj)):
                raise IndexError(f"Index {index} out of bounds for sequence of length {len(obj)}")
            return obj[index]
        except (ValueError, TypeError):
            pass
        except IndexError as e:
            raise IndexError(f"Failed accessing index '{attr}': {e}") from e

    if hasattr(obj, '__getitem__') and hasattr(obj, '__contains__'):
        try:
            if attr in obj:
                return obj[attr]
        except TypeError:
            pass

    attr_str = str(attr)
    if hasattr(obj, attr_str):
        return getattr(obj, attr_str)

    if create_path_if_not_exists:
        if default_mapping_constructor is None:
            raise ValueError("default_mapping_constructor required for path creation")
        if hasattr(obj, '__setitem__'):
            try:
                new_obj = default_mapping_constructor()
                obj[attr] = new_obj
                return new_obj
            except Exception as e:
                raise TypeError(
                    f"Failed to create path segment '{attr}' in object of type {type(obj).__name__}: {e}"
                ) from e
        else:
            raise TypeError(
                f"Object of type {type(obj).__name__} does not support path creation via item assignment"
            )

    raise AttributeError(
        f"Could not resolve attribute or item '{attr}' in object of type {type(obj).__name__}"
    )


ROOTPATH = KeyPath('/')
MAPPING_KEY = KeyPathToken.MAPPING_KEY
