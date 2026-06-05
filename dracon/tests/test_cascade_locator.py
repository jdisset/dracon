# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

"""Locator-backed `CascadeStrategy` (push face) + nested-key composition.

Exercised over a plain dict tree with a hand-rolled `TreeAdapter`, proving the
engine is adapter-agnostic (the same seam jeanplot's `ComponentTreeAdapter`
will fill in step 3)."""

from dataclasses import dataclass, field

import pytest

from dracon import (
    compose_nested_locators,
    loads,
    make_locator_cascade_strategy,
    parse_locator,
    register_cascade_strategy,
)


# ── a plain dict tree + its adapter (the seam) ───────────────────────────────


@dataclass
class Node:
    name: str
    mro: list[str]
    parent: "Node | None" = None
    kids: list["Node"] = field(default_factory=list)
    attrs: dict[str, object] = field(default_factory=dict)


class DictAdapter:
    def parent(self, node: Node) -> Node | None:
        return node.parent

    def children(self, node: Node) -> list[Node]:
        return node.kids

    def type_names(self, node: Node) -> list[str]:
        return [node.name, *node.mro]

    def attr(self, node: Node, name: str):
        return node.attrs.get(name)


def _link(parent: Node, *kids: Node) -> Node:
    for k in kids:
        k.parent = parent
    parent.kids = list(kids)
    return parent


@pytest.fixture
def tree() -> dict[str, Node]:
    label = Node("lbl", ["Label", "object"])
    panel = Node("api", ["PlotPanel", "Panel", "object"], attrs={"id": "p1"})
    _link(panel, label)
    root = Node("root", ["object"])
    _link(root, panel)
    return {"root": root, "panel": panel, "label": label}


@pytest.fixture
def strat():
    return make_locator_cascade_strategy("cascade_test", DictAdapter())


def _m(strat, key, node) -> bool:
    return strat.matches(strat.parse(key), node)


# ── matching semantics ───────────────────────────────────────────────────────


def test_type_and_mro_match(strat, tree):
    assert _m(strat, "PlotPanel", tree["panel"])  # exact type
    assert _m(strat, "Panel", tree["panel"])  # base in MRO
    assert not _m(strat, "Panel", tree["label"])  # wrong type


def test_child_vs_descendant(strat, tree):
    assert _m(strat, "PlotPanel > Label", tree["label"])  # direct child
    assert _m(strat, "PlotPanel Label", tree["label"])  # descendant
    assert _m(strat, "root Label", tree["label"])  # deeper descendant
    assert not _m(strat, "root > Label", tree["label"])  # not a direct child of root


def test_self_qualify(strat, tree):
    assert _m(strat, "PlotPanel[id=p1]", tree["panel"])
    assert not _m(strat, "PlotPanel[id=other]", tree["panel"])


def test_specificity_more_specific_wins(strat, tree):
    panel = tree["panel"]
    generic = strat.specificity(strat.parse("Panel"), panel)
    with_id = strat.specificity(strat.parse("Panel[id=p1]"), panel)
    assert with_id > generic


# ── full !cascade dispatch + merge ───────────────────────────────────────────


@pytest.fixture
def registered():
    register_cascade_strategy(make_locator_cascade_strategy("ltest", DictAdapter()))


def _panel() -> Node:
    return Node("api", ["PlotPanel", "Panel", "object"], attrs={"id": "p1"})


def test_cascade_invoke_specificity_order(registered):
    cfg = loads("""
rules: !cascade:ltest
  Panel: { color: blue, w: 1 }
  PlotPanel[id=p1]: { color: red }
""")
    props = dict(cfg["rules"].invoke(node=_panel()))
    assert props == {"color": "red", "w": 1}  # more specific overrode color, kept w


def test_cascade_peer_deep_merge(registered):
    # two same-strategy cascades meet at a `<<{+<}:` boundary -> union of rules
    cfg = loads("""
rules: !cascade:ltest
  Panel: { color: blue }
<<{+<}:
  rules: !cascade:ltest
    PlotPanel: { w: 9 }
""")
    props = dict(cfg["rules"].invoke(node=_panel()))
    assert props == {"color": "blue", "w": 9}


# ── nested-key composition (nesting == descendant combinator) ─────────────────


def test_nesting_combinators():
    body = {
        "PlotPanel": {
            "color": "blue",
            "Label": {"size": 10},  # descendant
            "> Inner": {"x": 1},  # child
            "~ Sibling": {"y": 2},  # sibling
            "&[id=p1]": {"z": 3},  # self-qualify
        }
    }
    flat = compose_nested_locators(body)
    assert flat[parse_locator("PlotPanel")] == {"color": "blue"}
    assert flat[parse_locator("PlotPanel Label")] == {"size": 10}
    assert flat[parse_locator("PlotPanel > Inner")] == {"x": 1}
    assert flat[parse_locator("PlotPanel ~ Sibling")] == {"y": 2}
    assert flat[parse_locator("PlotPanel[id=p1]")] == {"z": 3}


def test_nesting_matches_jstyle_flatten():
    # jeanplot's parse_jstyle_rule_tree emits Selector(" ".join(prefix)) for each
    # nested locator key and Selector(key) at top level -- i.e. nesting is the
    # descendant combinator. compose_nested_locators reproduces that flattening.
    body = {
        "PlotPanel": {"color": "blue", "Label": {"size": 10}},
        "Header": {"bg": "gray"},
    }
    flat = compose_nested_locators(body)
    expected = {
        parse_locator("PlotPanel"): {"color": "blue"},
        parse_locator("PlotPanel Label"): {"size": 10},
        parse_locator("Header"): {"bg": "gray"},
    }
    assert flat == expected
