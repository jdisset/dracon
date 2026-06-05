# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

import logging
import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Callable, NamedTuple

from dracon.tree_adapter import TreeAdapter, descend_value

logger = logging.getLogger(__name__)


class Specificity(NamedTuple):
    id_count: int = 0
    attr_class_count: int = 0
    type_count: int = 0


# ---------------------------------------------------------------------------
# Predicate: type + attribute conditions. Ported verbatim from jeanplot's
# _SimpleSelector so behaviour (operators, regexes, list semantics, specificity)
# is identical; the only change is testing against a TreeAdapter rather than a
# hardcoded component.
# ---------------------------------------------------------------------------

_ATTRIBUTE_SELECTOR_RE = re.compile(r"\[([^\]]+)\]")
_CONDITION_RE = re.compile(r"^\s*([^=~!<>*^$!]+)\s*(=[/~]?|!=|<=?|>=?|\*=|\^=|\$=)?\s*(.*)\s*$")
_REGEX_RE = re.compile(r"^(.*)/([ism]*)$")
_PRESENCE_RE = re.compile(r"^\s*(!)?([\w.-]+)\s*$")

Condition = tuple[str, str, str | None]  # (name, op, value)

_LIST_OPS = {"=", "!=", "=~", "^=", "$=", "*=", "=/", "<", "<=", ">", ">="}


def _regex_matches(actual_value: Any, pattern_details: str | None) -> bool:
    if actual_value is None or pattern_details is None:
        return False
    pattern, flags_str = pattern_details, ""
    m = _REGEX_RE.match(pattern_details)
    if m:
        pattern, flags_str = m.groups()
    re_flags = 0
    if "i" in flags_str:
        re_flags |= re.IGNORECASE
    if "m" in flags_str:
        re_flags |= re.MULTILINE
    if "s" in flags_str:
        re_flags |= re.DOTALL
    try:
        return bool(re.search(pattern, str(actual_value), re_flags))
    except re.error as exc:
        logger.warning("regex error in predicate: %s", exc)
        return False


def _value_matches(actual_value: Any, pattern_value: str | None, operator: str) -> bool:
    if pattern_value is None:
        return False
    pattern_is_none = pattern_value.lower() == "none"
    if operator == "=":
        return (actual_value is None and pattern_is_none) or (
            actual_value is not None and not pattern_is_none and str(actual_value) == pattern_value
        )
    if operator == "!=":
        return (
            actual_value is not None and (not pattern_is_none or str(actual_value) != pattern_value)
        ) or (actual_value is None and not pattern_is_none)
    if operator == "=~":
        return (
            actual_value is not None
            and not pattern_is_none
            and str(actual_value).lower() == pattern_value.lower()
        )
    return False


def _numeric_compare(actual_value: Any, pattern_value: str | None, operator: str) -> bool:
    if pattern_value is None:
        return False
    try:
        a, b = float(actual_value), float(pattern_value)
    except (ValueError, TypeError):
        return False
    cmp: dict[str, Callable[[float, float], bool]] = {
        "<": lambda x, y: x < y,
        "<=": lambda x, y: x <= y,
        ">": lambda x, y: x > y,
        ">=": lambda x, y: x >= y,
    }
    return cmp[operator](a, b)


def _apply_op(v: Any, op: str, p: str | None, attr_exists: bool) -> bool:
    if op == "exists":
        return attr_exists and bool(v)
    if op == "not_exists":
        return (not attr_exists) or (not bool(v))
    if op == "=":
        return attr_exists and _value_matches(v, p, "=")
    if op == "!=":
        return (not attr_exists) or _value_matches(v, p, "!=")
    if op == "=~":
        return attr_exists and _value_matches(v, p, "=~")
    if op == "^=":
        return (attr_exists and str(v).startswith(p)) if p is not None else False
    if op == "$=":
        return (attr_exists and str(v).endswith(p)) if p is not None else False
    if op == "*=":
        return (attr_exists and p in str(v)) if p is not None else False
    if op == "=/":
        return attr_exists and _regex_matches(v, p)
    if op in ("<", "<=", ">", ">="):
        return attr_exists and _numeric_compare(v, p, op)
    logger.warning("unknown operator '%s'", op)
    return False


def _check_condition(actual_value: Any, op: str, value_pattern: str | None) -> bool:
    attr_exists = actual_value is not None
    if isinstance(actual_value, (list, tuple, set)) and op in _LIST_OPS:
        if value_pattern is None:
            return False
        return any(_apply_op(item, op, value_pattern, attr_exists) for item in actual_value)
    return _apply_op(actual_value, op, value_pattern, attr_exists)


def _attr_path(node: Any, adapter: TreeAdapter, name: str) -> Any:
    parts = name.split(".")
    val = adapter.attr(node, parts[0])
    for part in parts[1:]:
        if val is None:
            return None
        val = descend_value(val, part)
    return val


@dataclass(frozen=True)
class Predicate:
    type_name: str | None
    conditions: tuple[Condition, ...]
    specificity: Specificity

    def matches(self, node: Any, adapter: TreeAdapter) -> bool:
        if self.type_name is not None and self.type_name not in adapter.type_names(node):
            return False
        return all(
            _check_condition(_attr_path(node, adapter, name), op, val)
            for name, op, val in self.conditions
        )

    def mro_level(self, node: Any, adapter: TreeAdapter) -> int:
        if self.type_name is not None:
            for i, t in enumerate(adapter.type_names(node)):
                if t == self.type_name:
                    return i
        return 1 << 30


def _parse_attributes(attr_content: str, raw: str) -> list[Condition]:
    out: list[Condition] = []
    conditions = [
        c.strip() for c in re.split(r",(?=(?:[^\"']*[\"'][^\"']*[\"'])*[^\"']*$)", attr_content)
    ]
    for cond in conditions:
        if not cond:
            continue
        mp = _PRESENCE_RE.match(cond)
        if mp:
            neg, name = mp.groups()
            out.append((name.strip(), "not_exists" if neg == "!" else "exists", None))
            continue
        mc = _CONDITION_RE.match(cond)
        if mc:
            name, op, val = mc.groups()
            if val and len(val) >= 2 and val.startswith(("'", '"')) and val.endswith(val[0]):
                val = val[1:-1]
            out.append((name.strip(), op or "=", val.strip()))
            continue
        logger.warning("could not parse attribute condition: '%s' in '%s'", cond, raw)
    return out


def _parse_segment(raw: str) -> tuple[str | None, list[Condition]]:
    matches = list(_ATTRIBUTE_SELECTOR_RE.finditer(raw))
    if not matches:
        return (raw if raw and raw != "*" else None), []
    type_selector: str | None = None
    if not raw.startswith("["):
        type_part = raw[: matches[0].start()].strip()
        if type_part and type_part != "*":
            type_selector = type_part
    last_end = matches[0].end()
    combined = matches[0].group(1)
    for m in matches[1:]:
        if m.start() == last_end:
            combined += "," + m.group(1)
            last_end = m.end()
        else:
            logger.warning("ignoring non-adjacent bracket in predicate: '%s'", raw)
            break
    return type_selector, _parse_attributes(combined, raw)


def _segment_specificity(type_selector: str | None, attributes: list[Condition]) -> Specificity:
    ids = sum(1 for n, _, _ in attributes if n == "id")
    others = sum(1 for n, _, _ in attributes if n != "id")
    return Specificity(ids, others, 1 if type_selector else 0)


def parse_predicate(segment: str) -> Predicate:
    raw = segment.strip()
    type_sel, attrs = _parse_segment(raw)
    return Predicate(type_sel, tuple(attrs), _segment_specificity(type_sel, attrs))


_ANY_PREDICATE = Predicate(None, (), Specificity())


# ---------------------------------------------------------------------------
# Locator: navigation (axis per step) + predicate per step.
# ---------------------------------------------------------------------------


class Axis(Enum):
    SELF = auto()
    CHILD = auto()
    DESCENDANT = auto()
    PARENT = auto()
    ANCESTOR = auto()
    SIBLING = auto()


@dataclass(frozen=True)
class Step:
    axis: Axis
    predicate: Predicate


@dataclass(frozen=True)
class Locator:
    rooted: bool
    steps: tuple[Step, ...]
    specificity: Specificity


def _read_chunk(s: str, i: int) -> tuple[str, int]:
    n = len(s)
    start = i
    depth = 0
    while i < n:
        c = s[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
        elif depth == 0 and (c.isspace() or c in ">~./"):
            break
        i += 1
    return s[start:i], i


def _tokenize(s: str) -> list[tuple[Axis, str | None]]:
    tokens: list[tuple[Axis, str | None]] = []
    i, n = 0, len(s)
    pending: Axis | None = None
    first = True
    while i < n:
        space = False
        while i < n and s[i].isspace():
            space = True
            i += 1
        if i >= n:
            break
        c = s[i]
        if c == ">":
            pending, i = Axis.CHILD, i + 1
            continue
        if c == "~":
            pending, i = Axis.SIBLING, i + 1
            continue
        if c == "/":
            pending, i = Axis.CHILD, i + 1
            continue
        if c == ".":
            if i + 1 < n and s[i + 1] == ".":
                tokens.append((Axis.PARENT, None))
                pending, first, i = None, False, i + 2
                continue
            pending, i = Axis.CHILD, i + 1
            continue
        if c == "^":
            if i + 1 < n and s[i + 1] == "[":
                chunk, i = _read_chunk(s, i + 1)
                tokens.append((Axis.ANCESTOR, chunk))
            else:
                tokens.append((Axis.PARENT, None))
                i += 1
            pending, first = None, False
            continue
        if s.startswith("closest(", i):
            j = i + len("closest(")
            depth, start = 1, j
            while j < n and depth:
                if s[j] == "(":
                    depth += 1
                elif s[j] == ")":
                    depth -= 1
                j += 1
            tokens.append((Axis.ANCESTOR, s[start : j - 1]))
            pending, first, i = None, False, j
            continue
        if pending is not None:
            axis = pending
        elif space and not first:
            axis = Axis.DESCENDANT
        else:
            axis = Axis.CHILD
        chunk, i = _read_chunk(s, i)
        tokens.append((axis, chunk))
        pending, first = None, False
    return tokens


def parse_locator(text: str) -> Locator:
    s = text.strip()
    rooted = s.startswith("/")
    if rooted:
        s = s[1:]
    steps: list[Step] = []
    for axis, chunk in _tokenize(s):
        if chunk is None:
            steps.append(Step(axis, _ANY_PREDICATE))
            continue
        name_run = chunk.split("[", 1)[0].strip()
        if name_run.startswith("**"):
            steps.append(Step(Axis.DESCENDANT, parse_predicate(chunk[2:])))
        else:
            steps.append(Step(axis, parse_predicate(chunk)))
    ids = sum(st.predicate.specificity.id_count for st in steps)
    ac = sum(st.predicate.specificity.attr_class_count for st in steps)
    tc = sum(st.predicate.specificity.type_count for st in steps)
    return Locator(rooted, tuple(steps), Specificity(ids, ac, tc))


# ---------------------------------------------------------------------------
# Evaluator.
# ---------------------------------------------------------------------------


def _node_key(node: Any) -> Any:
    try:
        hash(node)
        return node
    except TypeError:
        return id(node)


def _ancestry(node: Any, adapter: TreeAdapter) -> list[Any]:
    chain = [node]
    seen = {_node_key(node)}
    p = adapter.parent(node)
    while p is not None and _node_key(p) not in seen:
        chain.append(p)
        seen.add(_node_key(p))
        p = adapter.parent(p)
    return chain


def _root_of(node: Any, adapter: TreeAdapter) -> Any:
    return _ancestry(node, adapter)[-1]


def _descendants(node: Any, adapter: TreeAdapter) -> list[Any]:
    out: list[Any] = []
    seen = {_node_key(node)}
    queue = list(adapter.children(node))
    while queue:
        c = queue.pop(0)
        k = _node_key(c)
        if k in seen:
            continue
        seen.add(k)
        out.append(c)
        queue.extend(adapter.children(c))
    return out


def _nearest_ancestor(node: Any, pred: Predicate, adapter: TreeAdapter) -> list[Any]:
    seen: set[Any] = set()
    p = adapter.parent(node)
    while p is not None and _node_key(p) not in seen:
        seen.add(_node_key(p))
        if pred.matches(p, adapter):
            return [p]
        p = adapter.parent(p)
    return []


def _candidates(node: Any, step: Step, adapter: TreeAdapter) -> tuple[list[Any], bool]:
    """returns (candidates, prefiltered) -- prefiltered means the predicate is
    already enforced (ANCESTOR walks up to the matching node)."""
    axis = step.axis
    if axis == Axis.SELF:
        return [node], False
    if axis == Axis.CHILD:
        return list(adapter.children(node)), False
    if axis == Axis.DESCENDANT:
        return _descendants(node, adapter), False
    if axis == Axis.PARENT:
        p = adapter.parent(node)
        return ([p] if p is not None else []), False
    if axis == Axis.ANCESTOR:
        return _nearest_ancestor(node, step.predicate, adapter), True
    p = adapter.parent(node)  # SIBLING
    if p is None:
        return [], False
    nk = _node_key(node)
    return [c for c in adapter.children(p) if _node_key(c) != nk], False


def _step_frontier(frontier: list[Any], step: Step, adapter: TreeAdapter) -> list[Any]:
    out: list[Any] = []
    seen: set[Any] = set()
    for node in frontier:
        cands, prefiltered = _candidates(node, step, adapter)
        for c in cands:
            if not prefiltered and not step.predicate.matches(c, adapter):
                continue
            k = _node_key(c)
            if k in seen:
                continue
            seen.add(k)
            out.append(c)
    return out


def resolve(frame: Any, loc: Locator, adapter: TreeAdapter) -> list[Any]:
    frontier = [_root_of(frame, adapter) if loc.rooted else frame]
    for step in loc.steps:
        frontier = _step_frontier(frontier, step, adapter)
        if not frontier:
            return []
    return frontier


def matches(node: Any, loc: Locator, adapter: TreeAdapter) -> bool:
    steps = loc.steps
    if not steps:
        return True
    if not steps[-1].predicate.matches(node, adapter):
        return False
    cur = node
    for i in range(len(steps) - 1, 0, -1):
        combinator = steps[i].axis
        needed = steps[i - 1].predicate
        if combinator in (Axis.DESCENDANT, Axis.ANCESTOR):
            p = adapter.parent(cur)
            while p is not None and not needed.matches(p, adapter):
                p = adapter.parent(p)
            if p is None:
                return False
            cur = p
        elif combinator in (Axis.CHILD, Axis.PARENT):
            p = adapter.parent(cur)
            if p is None or not needed.matches(p, adapter):
                return False
            cur = p
        elif combinator == Axis.SIBLING:
            p = adapter.parent(cur)
            if p is None or not any(needed.matches(s, adapter) for s in adapter.children(p)):
                return False
        else:
            return False
    return True  # rootedness is a resolve-time anchor, not a relative-match concern


def get_inexactness(node: Any, loc: Locator, adapter: TreeAdapter) -> tuple[int, int]:
    """(skipped_ancestors, mro_distance) tiebreak; lower wins, skip dominates."""
    steps = loc.steps
    if not steps:
        return (0, 0)
    mro = steps[-1].predicate.mro_level(node, adapter)
    skip = 0
    cur = node
    for i in range(len(steps) - 1, 0, -1):
        combinator = steps[i].axis
        needed = steps[i - 1].predicate
        p = adapter.parent(cur)
        moved = 0
        if combinator in (Axis.CHILD, Axis.PARENT):
            if p is not None and not needed.matches(p, adapter):
                p = None
        else:
            while p is not None and not needed.matches(p, adapter):
                p = adapter.parent(p)
                moved += 1
        if p is None:
            break
        skip += moved
        mro += needed.mro_level(p, adapter)
        cur = p
    return (skip, mro)


def _distance(a: Any, b: Any, adapter: TreeAdapter) -> int:
    ca, cb = _ancestry(a, adapter), _ancestry(b, adapter)
    kb = {_node_key(n): i for i, n in enumerate(cb)}
    for i, n in enumerate(ca):
        j = kb.get(_node_key(n))
        if j is not None:
            return i + j
    return len(ca) + len(cb)


def resolve_one(frame: Any, loc: Locator, adapter: TreeAdapter) -> Any | None:
    found = resolve(frame, loc, adapter)
    if not found:
        return None
    if len(found) == 1:
        return found[0]

    def rank(n: Any) -> tuple[int, tuple[int, int]]:
        return (_distance(frame, n, adapter), get_inexactness(n, loc, adapter))

    ranked = sorted(found, key=rank)
    best = ranked[0]
    best_rank = rank(best)
    tied = sum(1 for n in found if rank(n) == best_rank)
    if tied > 1:
        logger.warning(
            "locator resolved ambiguously: %d nodes tied at best rank, returning first (dropped %d)",
            tied,
            tied - 1,
        )
    return best
