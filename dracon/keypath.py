from enum import Enum
from copy import deepcopy
from typing import List, Union, Hashable, Any
from ruamel.yaml.nodes import Node
from dracon.utils import node_repr, list_like, dict_like


class KeyPathToken(Enum):
    ROOT = 0
    UP = 1
    MAPPING_KEY = 2  # indicates that the path points to the key of a mapping, not the value


MAPPING_KEY = KeyPathToken.MAPPING_KEY


def escape_keypath_part(part: str) -> str:
    return part.replace('.', '\\.').replace('/', '\\/')


def unescape_keypath_part(part: str) -> str:
    return part.replace('\\.', '.').replace('\\/', '/')


# special symbols:


class KeyPath:
    def __init__(
        self, path: Union[str, List[Union[Hashable, KeyPathToken]]], simplify: bool = True
    ):
        self.is_simple = False
        if isinstance(path, str):
            self.parts = self._parse_string(path)
        elif isinstance(path, (list, tuple)):
            self.parts = list(path)  # Create a copy to avoid modifying the input
        else:
            self.parts = self._parse_string(str(path))
        if simplify:
            self.simplify()

    def _parse_string(self, path: str) -> List[Union[Hashable, KeyPathToken]]:
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
                    parts.append(self._convert_part(current_part))
                    current_part = ""
                parts.append(KeyPathToken.ROOT)
                dot_count = 0
            elif char == '.' and not escaped:
                if current_part:
                    parts.append(self._convert_part(current_part))
                    current_part = ""
                dot_count += 1
                if dot_count > 1:
                    parts.append(KeyPathToken.UP)
            else:
                current_part += char
                dot_count = 0
            escaped = False
        if current_part:
            parts.append(self._convert_part(current_part))
        return parts

    def _convert_part(self, part: str) -> Union[Hashable, KeyPathToken]:
        # if part.isdigit():
        # return int(part)
        return part

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

    def down(self, path: "str | KeyPath | KeyPathToken") -> 'KeyPath':
        self.is_simple = False
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

    # same as down
    def append(self, part: Union[Hashable, KeyPathToken]) -> 'KeyPath':
        return self.down(part)

    # same as down but not in place
    def __add__(self, other) -> 'KeyPath':
        return self.copy().down(other)

    def copy(self) -> 'KeyPath':
        return deepcopy(self)

    def simplify(self) -> 'KeyPath':
        if self.is_simple:
            return self
        simplified = []
        for part in self.parts:
            if part == KeyPathToken.ROOT:
                simplified = [KeyPathToken.ROOT]
            elif part == KeyPathToken.UP:
                if simplified and simplified[-1] not in (KeyPathToken.ROOT, KeyPathToken.UP):
                    if len(simplified) > 1 and simplified[-2] == KeyPathToken.MAPPING_KEY:
                        simplified.pop()  # popping a mapping key
                    simplified.pop()
                elif not simplified or simplified[-1] != KeyPathToken.ROOT:
                    simplified.append(KeyPathToken.UP)
            else:
                simplified.append(part)

        self.parts = simplified
        self.is_simple = True
        return self

    def simplified(self) -> 'KeyPath':
        new = KeyPath(self.parts, simplify=not self.is_simple)
        new.is_simple = True
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

    def get_obj(
        self, obj: Any, create_path_if_not_exists=False, default_mapping_constructor=None
    ) -> Any:

        if not self.is_simple:
            simplified = self.simplified()
            return simplified.get_obj(obj, create_path_if_not_exists, default_mapping_constructor)

        self.check_correctness()

        res = obj
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
            res = self._get_obj_impl(
                res, part, create_path_if_not_exists, default_mapping_constructor
            )
        return res

    def is_mapping_key(self) -> bool:
        if not self.is_simple:
            simplified = self.simplified()
            return simplified.is_mapping_key()
        if len(self.parts) < 2:
            return False
        return self.parts[-2] == KeyPathToken.MAPPING_KEY

    def removed_mapping_key(self) -> 'KeyPath':
        if not self.is_mapping_key():
            return self
        return KeyPath(self.parts[:-2]) + self.parts[-1]

    @staticmethod
    def _get_obj_impl(
        obj: Any, attr: Any, create_path_if_not_exists=False, default_mapping_constructor=None
    ) -> Any:
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
                if create_path_if_not_exists:
                    assert default_mapping_constructor is not None
                    obj[attr] = default_mapping_constructor()
                    return obj[attr]
                if isinstance(obj, Node):
                    raise AttributeError(
                        f'Could not find attribute {attr} in node \n{node_repr(obj)}'
                    )
                else:
                    raise AttributeError(f'Could not find attribute {attr} in {obj}')


ROOTPATH = KeyPath('/')
