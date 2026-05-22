# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

from typing import (
    Any,
    Callable,
    Literal,
)
from pydantic.dataclasses import dataclass
from functools import lru_cache

import re
from dracon.utils import ftrace, DictLike

INTERPOLATION_OPENERS = {'{': '}', '(': ')'}


class InterpolationError(Exception):
    pass


## {{{                    --     interpolation exprs     --

NOT_ESCAPED_REGEX = r"(?<!\\)(?:\\\\)*"


@lru_cache(maxsize=1024)
def transform_dollar_vars(text: str) -> str:
    """Replaces non-escaped $VAR patterns with ${VAR} for standard interpolation."""
    # pattern: $ followed by a valid python identifier start, then identifier chars.
    # ensures we don't match just '$' or '$123' etc.
    # also reject $$ escape: (?<!\$) ensures we don't match the second $ in $$VAR
    pattern = rf"(?<!\$){NOT_ESCAPED_REGEX}\$([a-zA-Z_][a-zA-Z0-9_]*)"

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


def scan_balanced(
    peek: Callable[[int], str],
    start: int,
    opener: str,
    closer: str,
    stop_at: str = '',
) -> int:
    """Return index past the matching close, or -1 if unbalanced or stop_at hit.
    `peek(i)` returns the char at offset i (empty string past EOF). Honors `\\`-escapes
    and skips quoted spans so braces inside strings don't unbalance the count."""
    depth = 1
    i = start
    while True:
        c = peek(i)
        if not c or c in stop_at:
            return -1
        if c == '\\':
            if not peek(i + 1):
                return -1
            i += 2
            continue
        if c == '"' or c == "'":
            quote = c
            i += 1
            while True:
                cc = peek(i)
                if not cc or cc in stop_at:
                    return -1
                if cc == '\\':
                    if not peek(i + 1):
                        return -1
                    i += 2
                    continue
                if cc == quote:
                    i += 1
                    break
                i += 1
            continue
        if c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1


def _dollar_is_escaped(peek: Callable[[int], str], pos: int) -> bool:
    bs = 0
    k = pos - 1
    while k >= 0 and peek(k) == '\\':
        bs += 1
        k -= 1
    if bs % 2 == 1:
        return True
    if pos > 0 and peek(pos - 1) == '$':
        pre_bs = 0
        k2 = pos - 2
        while k2 >= 0 and peek(k2) == '\\':
            pre_bs += 1
            k2 -= 1
        if pre_bs % 2 == 0:
            return True
    return False


def _str_peek(text: str) -> Callable[[int], str]:
    n = len(text)
    return lambda i: text[i] if 0 <= i < n else ''


@lru_cache(maxsize=1024)
def outermost_interpolation_exprs(
    text: str, interpolation_start_char='$', interpolation_boundary_chars=('{}', '()')
) -> list[InterpolationMatch]:
    if not fast_prescreen_interpolation_exprs_check(
        text, interpolation_start_char, interpolation_boundary_chars
    ):
        return []

    openers = {b[0]: b[1] for b in interpolation_boundary_chars}
    peek = _str_peek(text)
    matches: list[InterpolationMatch] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != interpolation_start_char or text[i + 1 : i + 2] not in openers:
            i += 1
            continue
        if _dollar_is_escaped(peek, i):
            i += 1
            continue
        opener = text[i + 1]
        end = scan_balanced(peek, i + 2, opener, openers[opener])
        if end < 0:
            i += 1
            continue
        matches.append(InterpolationMatch(i, end, text[i + 2 : end - 1]))
        i = end
    return matches


def unescape_dracon_specials(text: str) -> str:
    has_backslash_dollar = '\\$' in text
    has_double_dollar = '$$' in text
    if not has_backslash_dollar and not has_double_dollar:
        return text

    if has_backslash_dollar:
        text = re.sub(r'\\(\$\{)', r'\1', text)
        text = re.sub(r'\\(\$\()', r'\1', text)
        text = re.sub(r'\\(\$([a-zA-Z_][a-zA-Z0-9_]*))(?![a-zA-Z0-9_])', r'\1', text)
    if has_double_dollar:
        # $$ -> $ (must run after backslash unescaping so \$$ is handled correctly)
        text = re.sub(r'(?<!\\)\$\$', '$', text)
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
