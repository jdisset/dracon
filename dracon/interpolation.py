import ast
import re
from typing import Any, Dict, Callable, Optional, Tuple, List
from dracon.keypath import KeyPath
from dracon.utils import DictLike, ListLike
from pydantic.dataclasses import dataclass


class InterpolationError(Exception):
    pass


@dataclass
class KeypathMatch:
    start: int
    end: int
    expr: str

NOT_ESCAPED_REGEX = r"(?<!\\)(?:\\\\)*"
INVALID_KEYPATH_CHARS = r'[]() ,:=+-*%<>!&|^~@#$?;{}"\'`'
KEYPATH_START_CHAR = "@"
SPECIAL_KEYPATH_CHARS = './\\'  # Added backslash to handle escaping of itself

def find_keypaths(expr: str) -> List[KeypathMatch]:
    # Regex pattern to match keypaths
    pattern = (
        f"{NOT_ESCAPED_REGEX}{KEYPATH_START_CHAR}([^{re.escape(INVALID_KEYPATH_CHARS)}]|(?:\\\\.))*"
    )

    matches = []
    for match in re.finditer(pattern, expr):
        start, end = match.span()
        keypath = match.group()

        # Clean up escaping, but keep backslashes for special keypath characters
        cleaned_keypath = ''
        i = 0
        while i < len(keypath):
            if keypath[i] == '\\' and i + 1 < len(keypath):
                if keypath[i + 1] in SPECIAL_KEYPATH_CHARS:
                    cleaned_keypath += keypath[i : i + 2]
                    i += 2
                else:
                    cleaned_keypath += keypath[i + 1]
                    i += 2
            else:
                cleaned_keypath += keypath[i]
                i += 1

        # Check if the keypath ends with an odd number of backslashes
        if len(keypath) - len(keypath.rstrip('\\')) % 2 == 1:
            end -= 1
            cleaned_keypath = cleaned_keypath[:-1]

        matches.append(KeypathMatch(start, end, cleaned_keypath[1:]))

    return matches


@dataclass
class InterpolationMatch:
    start: int
    end: int
    expr: str

def outermost_interpolation_exprs(text: str) -> List[InterpolationMatch]:
    # match all ${...} expressions
    matches = list(re.finditer(r"\${[^}]+}", text))
    return [InterpolationMatch(m.start(), m.end(), m.group(0)[2:-1]) for m in matches]


def find_first_occurence(expr, *substrings) -> Optional[int]:
    pat = re.compile("|".join([NOT_ESCAPED_REGEX + re.escape(s) for s in substrings]))
    match = pat.search(expr)
    if match is None:
        return None
    else:
        return match.start()


