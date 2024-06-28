from enum import Enum
from copy import deepcopy
from typing import List, Union, Hashable

class KeyPathToken(Enum):
    ROOT = 0
    UP = 1

class KeyPath:
    def __init__(
        self, path: Union[str, List[Union[Hashable, KeyPathToken]]], simplify: bool = True
    ):
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

        for char in path:
            if char == '/':
                if current_part:
                    parts.append(self._convert_part(current_part))
                    current_part = ""
                parts.append(KeyPathToken.ROOT)
                dot_count = 0
            elif char == '.':
                if current_part:
                    parts.append(self._convert_part(current_part))
                    current_part = ""
                dot_count += 1
                if dot_count > 1:
                    parts.append(KeyPathToken.UP)
            else:
                current_part += char
                dot_count = 0
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
        self.parts.append(KeyPathToken.UP)
        if simplify:
            return self.simplify()
        return self

    def pop(self) -> Union[Hashable, KeyPathToken]:
        return self.parts.pop()

    def down(self, path: "str | KeyPath") -> 'KeyPath':
        if isinstance(path, KeyPath):
            self.parts.extend(path.parts)
        else:
            return self.down(KeyPath(path))
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
        simplified = []
        for part in self.parts:
            if part == KeyPathToken.ROOT:
                simplified = [KeyPathToken.ROOT]
            elif part == KeyPathToken.UP:
                if simplified and simplified[-1] not in (KeyPathToken.ROOT, KeyPathToken.UP):
                    simplified.pop()
                elif not simplified or simplified[-1] != KeyPathToken.ROOT:
                    simplified.append(KeyPathToken.UP)
            else:
                simplified.append(part)

        self.parts = simplified
        return self

    def simplified(self) -> 'KeyPath':
        return KeyPath(self.parts, simplify=True)

    def __str__(self) -> str:
        result = ''
        prev = None
        for part in self.parts:
            if part == KeyPathToken.ROOT:
                result += '/'
            elif part == KeyPathToken.UP:
                if prev == KeyPathToken.UP:
                    result += '.'
                else:
                    result += '..'
            else:
                if prev == KeyPathToken.ROOT or prev == KeyPathToken.UP or prev is None:
                    result += str(part)
                else:
                    result += '.' + str(part)
            prev = part
        return result

    def __repr__(self) -> str:
        return f"KeyPath('{self}')"


    def __len__(self) -> int:
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
        return self.parts[:len(other)] == other.parts

ROOTPATH = KeyPath('/')


