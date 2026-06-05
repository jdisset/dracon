# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

import logging
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from dracon.locator import (
    Axis,
    Locator,
    get_inexactness,
    matches,
    parse_locator,
    parse_predicate,
    resolve,
    resolve_one,
)
from dracon.tree_adapter import NodeTreeAdapter, descend_value, node_root
from jeanplot.core.style_selector import Selector, _SimpleSelector


# --------------------------------------------------------------------------- #
# in-isolation adapters
# --------------------------------------------------------------------------- #


@dataclass(eq=False)
class N:
    """plain tree node for engine-in-isolation tests."""

    name: str
    types: tuple[str, ...] = ()
    data: dict = field(default_factory=dict)
    kids: list = field(default_factory=list)
    parent: "N | None" = None


def tree(node: N) -> N:
    for k in node.kids:
        k.parent = node
        tree(k)
    return node


class NAdapter:
    def parent(self, node: N) -> "N | None":
        return node.parent

    def children(self, node: N) -> list[N]:
        return node.kids

    def type_names(self, node: N) -> list[str]:
        return [node.name, *node.types]

    def attr(self, node: N, name: str):
        return descend_value(node.data, name)


class ObjAdapter:
    """parity adapter: type_names == class MRO names, attr == getattr (mirrors
    jeanplot's _SimpleSelector exactly)."""

    def parent(self, node):
        return getattr(node, "parent", None)

    def children(self, node):
        return getattr(node, "_children", [])

    def type_names(self, node):
        return [c.__name__ for c in type(node).__mro__]

    def attr(self, node, name):
        return descend_value(node, name)


# --------------------------------------------------------------------------- #
# 1. parser round-trips
# --------------------------------------------------------------------------- #


def _axes(loc: Locator) -> list[Axis]:
    return [s.axis for s in loc.steps]


def test_parse_keypath_child_chain():
    loc = parse_locator("a.b.c")
    assert loc.rooted is False
    assert _axes(loc) == [Axis.CHILD, Axis.CHILD, Axis.CHILD]
    assert [s.predicate.type_name for s in loc.steps] == ["a", "b", "c"]


def test_parse_leading_slash_is_rooted():
    loc = parse_locator("/services.port")
    assert loc.rooted is True
    assert _axes(loc) == [Axis.CHILD, Axis.CHILD]


def test_parse_descendant_whitespace():
    assert _axes(parse_locator("A B")) == [Axis.CHILD, Axis.DESCENDANT]


def test_parse_child_combinator():
    assert _axes(parse_locator("A > B")) == [Axis.CHILD, Axis.CHILD]


def test_parse_sibling_combinator():
    assert _axes(parse_locator("A ~ B")) == [Axis.CHILD, Axis.SIBLING]


def test_parse_parent_spellings():
    assert _axes(parse_locator("..a")) == [Axis.PARENT, Axis.CHILD]
    assert _axes(parse_locator("^.a")) == [Axis.PARENT, Axis.CHILD]


def test_parse_ancestor_bracket_and_closest():
    a = parse_locator("^[type=Service].version")
    assert _axes(a) == [Axis.ANCESTOR, Axis.CHILD]
    assert a.steps[0].predicate.conditions == (("type", "=", "Service"),)
    c = parse_locator("closest([type=Service]).version")
    assert _axes(c) == [Axis.ANCESTOR, Axis.CHILD]
    assert c.steps[0].predicate.conditions == (("type", "=", "Service"),)


def test_parse_wildcards():
    star = parse_locator("a.*")
    assert _axes(star) == [Axis.CHILD, Axis.CHILD]
    assert star.steps[1].predicate.type_name is None
    dstar = parse_locator("a.**")
    assert _axes(dstar) == [Axis.CHILD, Axis.DESCENDANT]
    assert dstar.steps[1].predicate.type_name is None


def test_parse_predicate_on_wildcard():
    loc = parse_locator("/services.*[enabled=true].port")
    assert loc.rooted is True
    assert _axes(loc) == [Axis.CHILD, Axis.CHILD, Axis.CHILD]
    assert loc.steps[1].predicate.type_name is None
    assert loc.steps[1].predicate.conditions == (("enabled", "=", "true"),)


# --------------------------------------------------------------------------- #
# 2. every operator (parity vs _SimpleSelector)
# --------------------------------------------------------------------------- #

OP_SEGMENTS = [
    "[x=1]",
    "[x!=1]",
    "[x=2]",
    "[missing=1]",
    "[x>=2]",
    "[x>2]",
    "[x<5]",
    "[x<=1]",
    "[name^=ab]",
    "[name$=yz]",
    "[name*=cd]",
    "[tag=~HELLO]",
    "[tag=hello]",
    "[val=/^a.*z$/]",
    "[val=/^A.*Z$/i]",
    "[present]",
    "[!present]",
    "[!missing]",
    "[gone=none]",
    "[name!=none]",
    "[items=3]",
    "[items=9]",
    "[items>=2]",
]


@pytest.fixture
def op_objects():
    o1 = SimpleNamespace(
        x=1, name="abcdyz", tag="hello", val="abcz", present=True, items=[1, 2, 3], gone=None
    )
    o2 = SimpleNamespace(
        x=2, name="zzz", tag="world", val="nope", present=False, items=[], gone=None
    )
    return [o1, o2]


@pytest.mark.parametrize("seg", OP_SEGMENTS)
def test_operator_parity(seg, op_objects):
    adapter = ObjAdapter()
    mine = parse_predicate(seg)
    theirs = _SimpleSelector(seg)
    assert mine.specificity == theirs.specificity
    for o in op_objects:
        assert mine.matches(o, adapter) == theirs.matches(o), (seg, vars(o))


# --------------------------------------------------------------------------- #
# 3. each axis (engine in isolation)
# --------------------------------------------------------------------------- #


@pytest.fixture
def small_tree():
    return tree(
        N(
            "root",
            kids=[
                N(
                    "services",
                    kids=[
                        N("api", types=("Service",), data={"port": 8080, "enabled": "true"}),
                        N("worker", types=("Service",), data={"port": 8081, "enabled": "false"}),
                        N("cron", types=("Service",), data={"port": 8082, "enabled": "true"}),
                    ],
                ),
                N("db", kids=[N("primary", data={"port": 5432})]),
            ],
        )
    )


def test_axis_child(small_tree):
    a = NAdapter()
    out = resolve(small_tree, parse_locator("services"), a)
    assert [n.name for n in out] == ["services"]


def test_axis_descendant(small_tree):
    a = NAdapter()
    out = resolve(small_tree, parse_locator("**[port>=8082]"), a)
    assert {n.name for n in out} == {"cron"}


def test_axis_parent(small_tree):
    a = NAdapter()
    api = small_tree.kids[0].kids[0]
    out = resolve(api, parse_locator(".."), a)
    assert [n.name for n in out] == ["services"]


def test_axis_ancestor(small_tree):
    a = NAdapter()
    api = small_tree.kids[0].kids[0]
    out = resolve(api, parse_locator("closest(root)"), a)
    assert [n.name for n in out] == ["root"]


def test_axis_sibling(small_tree):
    a = NAdapter()
    api = small_tree.kids[0].kids[0]
    out = resolve(api, parse_locator("~ Service"), a)
    assert {n.name for n in out} == {"worker", "cron"}


def test_predicate_fanout(small_tree):
    a = NAdapter()
    out = resolve(small_tree, parse_locator("/services.*[enabled=true]"), a)
    assert {n.name for n in out} == {"api", "cron"}


def test_self_axis_matches_frame(small_tree):
    a = NAdapter()
    assert matches(small_tree, parse_locator(""), a) is True


def test_matches_ignores_rootedness(small_tree):
    """matches() is a relative ancestor-chain test; a rooted locator must not
    spuriously fail just because the leftmost match has a (root) parent."""
    a = NAdapter()
    api = small_tree.kids[0].kids[0]
    assert matches(api, parse_locator("/services.api"), a) is True


# --------------------------------------------------------------------------- #
# 4. descendant non-adjacency + matching parity vs Selector
# --------------------------------------------------------------------------- #


class Root:
    def __init__(self, **kw):
        self.__dict__.update(kw)
        self.parent = None
        self._children = []


class Outer(Root):
    pass


class Mid(Root):
    pass


class Inner(Root):
    pass


def _link(parent, *kids):
    for k in kids:
        k.parent = parent
        parent._children.append(k)
    return parent


@pytest.fixture
def class_tree():
    inner = Inner(role="leaf")
    mid = Mid()
    outer = Outer(role="top")
    _link(mid, inner)
    _link(outer, mid)
    return outer, mid, inner


PARITY_SELECTORS = [
    "Inner",
    "Outer Inner",
    "Outer Mid Inner",
    "Outer Inner",
    "Mid Inner",
    "Root Inner",
    "Outer[role=top] Inner",
    "Outer[role=top] Inner[role=leaf]",
    "Mid[role=top] Inner",
    "Outer[missing] Inner",
    "Inner[role=leaf]",
]


@pytest.mark.parametrize("sel", PARITY_SELECTORS)
def test_matching_parity_vs_selector(sel, class_tree):
    _, _, inner = class_tree
    adapter = ObjAdapter()
    assert matches(inner, parse_locator(sel), adapter) == Selector(sel).matches(inner)


@pytest.mark.parametrize("sel", PARITY_SELECTORS)
def test_specificity_parity_vs_selector(sel):
    assert parse_locator(sel).specificity == Selector(sel).specificity


def test_descendant_non_adjacent(class_tree):
    """Outer is the grandparent of Inner (skips Mid): descendant must match
    non-adjacent ancestors."""
    _, _, inner = class_tree
    adapter = ObjAdapter()
    assert matches(inner, parse_locator("Outer Inner"), adapter) is True
    # but a CHILD combinator requires the immediate parent
    assert matches(inner, parse_locator("Outer > Inner"), adapter) is False
    assert matches(inner, parse_locator("Mid > Inner"), adapter) is True


def test_inexactness_parity_vs_selector(class_tree):
    _, _, inner = class_tree
    adapter = ObjAdapter()
    for sel in ["Outer Inner", "Mid Inner", "Root Inner"]:
        assert get_inexactness(inner, parse_locator(sel), adapter) == Selector(sel).get_inexactness(
            inner
        )


# --------------------------------------------------------------------------- #
# 5. ambiguity ordering
# --------------------------------------------------------------------------- #


def test_resolve_one_prefers_nearest():
    """two nodes tagged 'x' at different tree distances from the frame; the
    nearer one wins."""
    near = N("near", types=("Target",))
    far = N("far", types=("Target",))
    root = tree(N("root", kids=[N("branch", kids=[near]), far]))
    frame = near.parent  # 'branch'
    a = NAdapter()
    best = resolve_one(frame, parse_locator("/branch.near"), a)
    assert best is not None and best.name == "near"
    # rooted descendant matches both; nearest (near, sharing 'branch') ranks first
    best2 = resolve_one(frame, parse_locator("/**Target"), a)
    assert best2 is not None and best2.name == "near"
    assert root is not None


def test_resolve_one_logs_on_tie(caplog):
    left = N("a", types=("T",))
    right = N("b", types=("T",))
    root = tree(N("root", kids=[N("frame"), left, right]))
    frame = root.kids[0]
    a = NAdapter()
    with caplog.at_level(logging.WARNING, logger="dracon.locator"):
        best = resolve_one(frame, parse_locator("/**T"), a)
    assert best is not None
    assert any("ambiguous" in r.message for r in caplog.records)


def test_resolve_one_none_on_no_match(small_tree):
    a = NAdapter()
    assert resolve_one(small_tree, parse_locator("/nonexistent"), a) is None


# --------------------------------------------------------------------------- #
# 6. cycle guard
# --------------------------------------------------------------------------- #


def test_ancestor_cycle_guard_terminates():
    a = N("a")
    b = N("b")
    a.parent = b
    b.parent = a  # cycle
    adapter = NAdapter()
    # ancestor walk must stop instead of looping forever
    assert resolve(a, parse_locator("^[nonexistent]"), adapter) == []
    assert resolve(a, parse_locator(".."), adapter) == [b]


def test_descendant_cycle_guard_terminates():
    a = N("a", types=("X",))
    b = N("b")
    a.kids = [b]
    b.kids = [a]  # cycle
    a.parent = b
    b.parent = a
    adapter = NAdapter()
    # descendants exclude self; the a->b->a cycle must not loop forever
    out = resolve(a, parse_locator("**"), adapter)
    assert [n.name for n in out] == ["b"]


# --------------------------------------------------------------------------- #
# 7. canonical NodeTreeAdapter over nested dict/list
# --------------------------------------------------------------------------- #


@pytest.fixture
def dict_root():
    data = {
        "region": "us-east-1",
        "services": {
            "api": {"enabled": "true", "port": 8080},
            "worker": {"enabled": "false", "port": 8081},
            "cron": {"enabled": "true", "port": 8082},
        },
        "pipeline": [
            {"id": "load", "out": "raw"},
            {"id": "clean", "out": "tidy"},
        ],
    }
    return node_root(data)


def test_node_adapter_keypath_resolve(dict_root):
    a = NodeTreeAdapter()
    out = resolve(dict_root, parse_locator("/services.api.port"), a)
    assert [n.value for n in out] == [8080]


def test_node_adapter_predicate_fanout(dict_root):
    a = NodeTreeAdapter()
    out = resolve(dict_root, parse_locator("/services.*[enabled=true].port"), a)
    assert sorted(n.value for n in out) == [8080, 8082]


def test_node_adapter_list_index_and_parent(dict_root):
    a = NodeTreeAdapter()
    clean = resolve(dict_root, parse_locator("/pipeline.*[id=clean].out"), a)
    assert [n.value for n in clean] == ["tidy"]


def test_node_adapter_parent_stops_at_root(dict_root):
    a = NodeTreeAdapter()
    assert a.parent(dict_root) is None


def test_node_adapter_dedup_by_path(dict_root):
    a = NodeTreeAdapter()
    # ** then a child re-reaches nodes; results must be unique by path
    out = resolve(dict_root, parse_locator("/**[port>=8080]"), a)
    paths = [str(n.path) for n in out]
    assert len(paths) == len(set(paths)) == 3
