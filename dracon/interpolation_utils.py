# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

from typing import (
    Any,
    Dict,
    Literal,
)
from pydantic.dataclasses import dataclass
from functools import lru_cache

import pyparsing as pp
import re
from dracon.utils import ftrace, DictLike


class InterpolationError(Exception):
    pass


BASE_DRACON_SYMBOLS: Dict[str, Any] = {}

## {{{                    --     interpolation exprs     --

NOT_ESCAPED_REGEX = r"(?<!\\)(?:\\\\)*"


@lru_cache(maxsize=1024)
def transform_dollar_vars(text: str) -> str:
    """Replaces non-escaped $VAR patterns with ${VAR} for standard interpolation."""
    # pattern: $ followed by a valid python identifier start, then identifier chars.
    # ensures we don't match just '$' or '$123' etc.
    pattern = rf"{NOT_ESCAPED_REGEX}\$([a-zA-Z_][a-zA-Z0-9_]*)"

    def repl(match):
        var_name = match.group(1)
        return f"${{{var_name}}}"  # transform $VAR -> ${VAR}

    return re.sub(pattern, repl, text)


@dataclass
class InterpolationMatch:
    start: int
    end: int
    expr: str

    def contains(self, pos: int) -> bool:
        return self.start <= pos < self.end


def fast_prescreen_interpolation_exprs_check(  # 5000x faster prescreen but very simple and limited
    text: str, interpolation_start_char='$', interpolation_boundary_chars=('{}', '()')
) -> bool:
    start_patterns = [interpolation_start_char + bound[0] for bound in interpolation_boundary_chars]
    for start_pattern in start_patterns:
        if start_pattern in text:
            return True
    return False


@lru_cache(maxsize=1024)
def outermost_interpolation_exprs(
    text: str, interpolation_start_char='$', interpolation_boundary_chars=('{}', '()')
) -> list[InterpolationMatch]:
    matches = []
    if not fast_prescreen_interpolation_exprs_check(
        text, interpolation_start_char, interpolation_boundary_chars
    ):
        return matches

    scanner = pp.MatchFirst(
        [
            pp.originalTextFor(pp.nestedExpr(bounds[0], bounds[1]))
            for bounds in interpolation_boundary_chars
        ]
    )
    scanner = pp.Combine(interpolation_start_char + scanner)

    # handle escaped characters
    for match_obj, start, end in scanner.scanString(text):
        num_backslashes = 0
        k = start - 1
        while k >= 0 and text[k] == '\\':
            num_backslashes += 1
            k -= 1
        if num_backslashes % 2 == 1:
            continue
        matches.append(InterpolationMatch(start, end, match_obj[0][2:-1]))

    return sorted(matches, key=lambda m: m.start)


def unescape_dracon_specials(text: str) -> str:
    if '\\$' not in text:
        return text

    text = re.sub(r'\\(\$\{)', r'\1', text)
    text = re.sub(r'\\(\$\()', r'\1', text)
    text = re.sub(r'\\(\$([a-zA-Z_][a-zA-Z0-9_]*))(?![a-zA-Z0-9_])', r'\1', text)
    return text


def outermost_comptime_interpolations(text: str) -> list[InterpolationMatch]:
    return outermost_interpolation_exprs(
        text, interpolation_start_char='$', interpolation_boundary_chars=('()',)
    )


def outermost_lazy_interpolations(text: str) -> list[InterpolationMatch]:
    return outermost_interpolation_exprs(
        text, interpolation_start_char='$', interpolation_boundary_chars=('{}',)
    )


##────────────────────────────────────────────────────────────────────────────}}}
## {{{             --     find references [@,&](keypaths, anchors)     --

# Find all field references in an expression string and replace them with a function call


@dataclass
class ReferenceMatch:
    start: int
    end: int
    expr: str
    symbol: Literal['@', '&']


INVALID_KEYPATH_CHARS = r'[]() ,+-*%<>!&|^~@#$?;{}"\'`'
SPECIAL_KEYPATH_CHARS = './\\'


def find_field_references(expr: str) -> list[ReferenceMatch]:
    # Regex pattern to match keypaths
    pattern = f"{NOT_ESCAPED_REGEX}[&@]([^{re.escape(INVALID_KEYPATH_CHARS)}]|(?:\\\\.))*"

    matches = []
    for match in re.finditer(pattern, expr):
        start, end = match.span()
        full_match = match.group()
        keypath = full_match[1:]
        symbol = full_match[0]
        assert symbol in ('@', '&')

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

        matches.append(ReferenceMatch(start, end, cleaned_keypath, symbol))

    return matches


##────────────────────────────────────────────────────────────────────────────}}}
## {{{                --     find interpolable variables     --

# an interpolable variable is a special $VARIABLE defined by dracon (or the user)
# they are immmediately replaced by their value when found in the expression string
# pattern is $ + CAPITAL_LETTER + [a-zA-Z0-9_]


@dataclass
class VarMatch:
    start: int
    end: int
    varname: str


def find_interpolable_variables(expr: str) -> list[VarMatch]:
    matches = []
    for match in re.finditer(rf"{NOT_ESCAPED_REGEX}\$[A-Z][a-zA-Z0-9_]*", expr):
        start, end = match.span()
        matches.append(VarMatch(start, end, match.group()))
    return matches


def resolve_interpolable_variables(expr: str, symbols: DictLike[str, Any]) -> str:
    var_matches = find_interpolable_variables(expr)
    if not var_matches:
        return expr
    offset = 0
    for match in var_matches:
        if match.varname not in symbols:
            raise InterpolationError(f"Variable {match.varname} not found in {symbols=}")
        newexpr = str(symbols[match.varname])
        expr = expr[: match.start + offset] + newexpr + expr[match.end + offset :]
        original_len = match.end - match.start
        offset += len(newexpr) - original_len
    return expr


##────────────────────────────────────────────────────────────────────────────}}}
