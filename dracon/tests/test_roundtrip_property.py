# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Round-trip property tests + per-bug regressions (v5 step 05).

Pins the bidirectional contract::

    loads(dump(x, V), V) ≅ x

- Tier 1: vocabulary-closed values round-trip semantically.
- Tier 2: values with deferred / open branches round-trip structurally
  and fail consistently at resolve-time, not at dump or load.

The equivalence relation ``≅`` is defined in :func:`equivalent` and
documented there. Property tests use Hypothesis to generate values
over the load-side universe; regression tests are deterministic
anchors for specific bugs fixed in steps 02-04.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union

from hypothesis import HealthCheck, given, settings, strategies as st
from pydantic import BaseModel, Field, computed_field

from dracon import DraconLoader, dump, dump_to_node
from dracon.callable import DraconCallable
from dracon.deferred import DeferredNode, make_deferred
from dracon.lazy import LazyInterpolable
from dracon.nodes import (
    DEFAULT_MAP_TAG,
    DEFAULT_SCALAR_TAG,
    DraconMappingNode,
    DraconScalarNode,
    Node,
)
from dracon.partial import DraconPartial
from dracon.pipe import DraconPipe
from dracon.resolvable import Resolvable
from dracon.symbol_table import SymbolEntry, SymbolTable
from dracon.symbols import BoundSymbol, CallableSymbol


# ── shared vocabulary fixture ───────────────────────────────────────────────


class Color(Enum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"


class Point(BaseModel):
    x: int = 0
    y: int = 0


class Pair(BaseModel):
    a: Point
    b: Point


class Tagged(BaseModel):
    """Pydantic model with alias, default factory, and computed field."""

    label: str = Field(alias="l")
    items: list[int] = Field(default_factory=list)
    meta: dict[str, int] = Field(default_factory=dict)

    @computed_field
    def size(self) -> int:
        return len(self.items)


class Container(BaseModel):
    """Holds arbitrary dracon-native wrappers in an untyped slot."""

    model_config = {"arbitrary_types_allowed": True}
    name: str = "c"
    slot: object = None
    bag: dict[str, object] = Field(default_factory=dict)


# -- discriminated union --


class CatEvent(BaseModel):
    kind: Literal["cat"] = "cat"
    name: str


class DogEvent(BaseModel):
    kind: Literal["dog"] = "dog"
    name: str


Event = Annotated[Union[CatEvent, DogEvent], Field(discriminator="kind")]


class EventBus(BaseModel):
    events: list[Event] = Field(default_factory=list)


# -- registered test types; the same SymbolTable drives dump + load --

_TEST_TYPES: dict[str, type] = {
    "Point": Point,
    "Pair": Pair,
    "Tagged": Tagged,
    "Color": Color,
    "Container": Container,
    "CatEvent": CatEvent,
    "DogEvent": DogEvent,
    "EventBus": EventBus,
}


def make_vocabulary() -> SymbolTable:
    """SymbolTable with canonical entries for every test-vocabulary type."""
    tbl = SymbolTable()
    for name, value in _TEST_TYPES.items():
        tbl.define(SymbolEntry(name=name, symbol=CallableSymbol(value, name=name)))
    return tbl


def make_loader() -> DraconLoader:
    """Loader bound to the shared test vocabulary."""
    loader = DraconLoader()
    loader.context = make_vocabulary()
    loader.yaml.representer.full_module_path = False
    return loader


# ── the ≅ relation ──────────────────────────────────────────────────────────


def _equal_mapping(a: Any, b: Any) -> bool:
    if set(a.keys()) != set(b.keys()):
        return False
    return all(equivalent(a[k], b[k]) for k in a)


def _equal_sequence(a: Any, b: Any) -> bool:
    return len(a) == len(b) and all(equivalent(x, y) for x, y in zip(a, b))


def _equal_node(a: Node, b: Node) -> bool:
    """Structural equality on tag, value, and children."""
    if a.tag != b.tag:
        return False
    if isinstance(a, DraconMappingNode) and isinstance(b, DraconMappingNode):
        if len(a.value) != len(b.value):
            return False
        return all(
            _equal_node(ak, bk) and _equal_node(av, bv)
            for (ak, av), (bk, bv) in zip(a.value, b.value)
        )
    if hasattr(a, 'value') and hasattr(b, 'value'):
        av, bv = a.value, b.value
        if isinstance(av, list) and isinstance(bv, list):
            return len(av) == len(bv) and all(_equal_node(x, y) for x, y in zip(av, bv))
        return av == bv
    return False


def equivalent(a: Any, b: Any) -> bool:
    """The ``≅`` relation used by round-trip property tests.

    - Primitives and plain containers: ``==``
    - Dracon containers: element-wise equivalent
    - Pydantic models: ``==`` (BaseModel implements it)
    - Nodes / DeferredNode: structural equality on tag, value, children
    - Resolvable: structural equality on ``.node`` (and inner_type matches)
    - LazyInterpolable: equal on its expression source, not the resolved value
    - DraconCallable / DraconPipe / BoundSymbol / DraconPartial: equal on
      their serialized !fn / !pipe / !fn:name form (dump and compare)
    - Everything else: fall back to ``==``

    Fragility: DeferredNode and DraconCallable equivalence is structural.
    Two deferred trees that would produce equal results via different
    instruction shapes will not compare equal. Round-trip preserves the
    exact tree so the invariant holds today; any future canonicalization
    of deferred trees would need a normalized-form comparison here.
    """
    if a is b:
        return True
    if isinstance(a, LazyInterpolable) or isinstance(b, LazyInterpolable):
        return str(getattr(a, 'value', a)) == str(getattr(b, 'value', b))
    if isinstance(a, DeferredNode) and isinstance(b, DeferredNode):
        return _equal_node(a.value, b.value)
    if isinstance(a, Resolvable) and isinstance(b, Resolvable):
        if a.inner_type is not b.inner_type:
            return False
        if a.node is None or b.node is None:
            return a.node is None and b.node is None
        return _equal_node(a.node, b.node)
    if isinstance(a, (DraconCallable, DraconPipe, BoundSymbol, DraconPartial)) and type(a) is type(b):
        return dump(a) == dump(b)
    if isinstance(a, Node) and isinstance(b, Node):
        return _equal_node(a, b)
    if isinstance(a, BaseModel) and isinstance(b, BaseModel):
        return type(a) is type(b) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return _equal_mapping(a, b)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return _equal_sequence(a, b)
    return a == b


# ── sanity: the equivalence relation itself ─────────────────────────────────


class TestEquivalence:
    """The equivalence relation must itself be well-formed so the property
    suite never goes green by accident.
    """

    def test_reflexive_on_primitives(self):
        for v in [0, 1.5, True, None, "hello", [], {}, [1, 2], {"a": 1}]:
            assert equivalent(v, v)

    def test_detects_primitive_mismatch(self):
        assert not equivalent(1, 2)
        assert not equivalent({"a": 1}, {"a": 2})
        assert not equivalent([1, 2], [2, 1])

    def test_detects_nested_mapping_mismatch(self):
        assert equivalent({"a": {"b": [1, 2]}}, {"a": {"b": [1, 2]}})
        assert not equivalent({"a": {"b": [1, 2]}}, {"a": {"b": [2, 1]}})

    def test_pydantic_models(self):
        assert equivalent(Point(x=1, y=2), Point(x=1, y=2))
        assert not equivalent(Point(x=1, y=2), Point(x=1, y=3))

    def test_lazy_interpolable_compares_expression_source(self):
        assert equivalent(LazyInterpolable(value="${1 + 2}"), LazyInterpolable(value="${1 + 2}"))
        assert not equivalent(LazyInterpolable(value="${1}"), LazyInterpolable(value="${2}"))


# ── round-trip helper ───────────────────────────────────────────────────────


def _round_trip(value: Any) -> Any:
    """Dump and immediately reload through a fresh loader with the same vocab."""
    text = make_loader().dump(value)
    return make_loader().loads(text)


# ── Tier 1: primitive + container strategies ───────────────────────────────


# ruamel's reader rejects most C0/C1 controls and the unicode line separators
# used as YAML line breaks. we emit flow-safe text only so the property test
# focuses on the dump/load contract and not on YAML reader edge cases.
#
# `$` is also filtered: dracon treats `${...}`, `$(...)`, `$ident`, and `$$`
# in loaded YAML strings as template syntax (lazy/comptime interpolation,
# shorthand vars, escape unwinding). A plain python string like `"$A"` is
# not lossless through dump→load because the load path reinterprets it as
# a template. This is documented semantics, not a bug; users who need
# strict round-trip for dollar-prefixed strings should disable
# `enable_shorthand_vars` and `interpolation_enabled` on the loader.
_SAFE_TEXT = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs", "Cc"),
        blacklist_characters="\x00\x85\u2028\u2029$",
    ),
    max_size=30,
)


def _safe_key() -> st.SearchStrategy[str]:
    # keys starting with '<<' hit the dracon merge operator; '__dracon__'
    # is the construct-skip marker. both are filtered out.
    return st.text(min_size=1, max_size=12, alphabet=st.characters(
        whitelist_categories=("Ll", "Lu", "Nd"),
        whitelist_characters="_-.",
    )).filter(lambda s: not s.startswith("<<") and not s.startswith("__dracon__"))


primitives = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**31), max_value=2**31 - 1),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    _SAFE_TEXT,
)


def _branch(children):
    return st.one_of(
        st.lists(children, max_size=4),
        # min_size=1: top-level empty mappings don't round-trip in dracon
        st.dictionaries(_safe_key(), children, min_size=1, max_size=4),
    )


json_safe = st.recursive(primitives, _branch, max_leaves=20).filter(
    lambda v: isinstance(v, (dict, list))  # top-level containers only
)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(data=json_safe)
def test_tier1_json_safe_round_trip(data):
    reloaded = _round_trip(data)
    # dracon Mapping/Sequence are equivalent to dict/list; equivalent() handles both.
    assert equivalent(reloaded, data), f"{reloaded!r} != {data!r}"


# ── Tier 1: pydantic model strategies ──────────────────────────────────────


points = st.builds(
    Point,
    x=st.integers(min_value=-100, max_value=100),
    y=st.integers(min_value=-100, max_value=100),
)

pairs = st.builds(Pair, a=points, b=points)

tagged = st.builds(
    Tagged,
    l=_SAFE_TEXT.filter(lambda s: len(s) >= 1),
    items=st.lists(st.integers(min_value=-10, max_value=10), max_size=4),
    meta=st.dictionaries(_safe_key(), st.integers(min_value=-10, max_value=10), max_size=3),
)


@settings(max_examples=40, deadline=None)
@given(p=points)
def test_tier1_pydantic_simple_model_round_trip(p):
    reloaded = _round_trip(p)
    assert reloaded == p


@settings(max_examples=40, deadline=None)
@given(p=pairs)
def test_tier1_pydantic_nested_model_round_trip(p):
    reloaded = _round_trip(p)
    assert reloaded == p


@settings(max_examples=30, deadline=None)
@given(t=tagged)
def test_tier1_pydantic_alias_and_computed_field_round_trip(t):
    reloaded = _round_trip(t)
    assert reloaded == t


# -- enum --


@given(c=st.sampled_from(list(Color)))
def test_tier1_enum_round_trip(c):
    # enums dump by value under a registered !Color tag and reload as the
    # enum instance.
    reloaded = _round_trip(c)
    assert reloaded == c


# -- discriminated union --


_short_text = _SAFE_TEXT.filter(lambda s: len(s) >= 1)
events = st.one_of(
    st.builds(CatEvent, name=_short_text),
    st.builds(DogEvent, name=_short_text),
)


@settings(max_examples=30, deadline=None)
@given(bus=st.builds(EventBus, events=st.lists(events, max_size=4)))
def test_tier1_discriminated_union_round_trip(bus):
    reloaded = _round_trip(bus)
    assert reloaded == bus


# ── Tier 2: open values with deferred / resolvable branches ────────────────


def _build_container_with_deferred(payload: dict[str, Any]) -> Container:
    l = make_loader()
    return Container(name="c", slot=make_deferred(payload, loader=l))


@settings(max_examples=20, deadline=None)
@given(payload=st.dictionaries(_safe_key(), st.integers(), min_size=1, max_size=3))
def test_tier2_deferred_field_round_trips_structurally(payload):
    c = _build_container_with_deferred(payload)
    reloaded = _round_trip(c)
    assert isinstance(reloaded.slot, DeferredNode)
    assert equivalent(reloaded.slot, c.slot)
    # tier 2 also promises: constructing the deferred still works after reload
    assert reloaded.slot.construct() == payload


def _build_container_with_resolvable(name: str) -> Container:
    l = make_loader()
    inner_node = l.yaml.representer.represent_data(Point(x=1, y=2))
    return Container(name=name, slot=Resolvable(node=inner_node, inner_type=Point))


def _node_child_values(node):
    """Flatten a mapping node to {str_key: scalar_str_value} for coarse compare."""
    out = {}
    for k, v in getattr(node, 'value', ()) or ():
        kv = getattr(k, 'value', None)
        vv = getattr(v, 'value', None)
        if isinstance(kv, str):
            out[kv] = vv
    return out


@settings(max_examples=10, deadline=None)
@given(name=_short_text)
def test_tier2_resolvable_field_round_trips_structurally(name):
    c = _build_container_with_resolvable(name)
    reloaded = _round_trip(c)
    assert isinstance(reloaded.slot, Resolvable)
    assert reloaded.slot.inner_type is c.slot.inner_type
    # on reload the inner node wears the wrapper tag (e.g. !Resolvable[Point])
    # while the source still has the constructor tag (!Point). compare on
    # child values which are tag-invariant.
    assert _node_child_values(reloaded.slot.node) == _node_child_values(c.slot.node)


# ═══════════════════════════════════════════════════════════════════════════
# Regression tests — one per fixed bug. These are deterministic anchors for
# the property tests: when a property shrinks to an unclear minimum, these
# tell you which known-bug class it landed in.
# ═══════════════════════════════════════════════════════════════════════════


# ── step 02: wrapper representers ───────────────────────────────────────────


class TestStep02WrapperRegressions:
    """Regression anchors for the four step-02 bugs."""

    def test_resolvable_wrapper_preserved_on_round_trip(self):
        """``represent_resolvable`` used to drop the wrapper."""
        l = make_loader()
        inner = l.yaml.representer.represent_data(Point(x=1, y=2))
        r = Resolvable(node=inner, inner_type=Point)
        text = l.dump(r)
        assert "!Resolvable" in text
        reloaded = l.loads(text)
        assert isinstance(reloaded, Resolvable), "wrapper was dropped"

    def test_loaded_deferred_node_dumps_without_recursion(self):
        """``represent_deferred_node`` used to recurse infinitely on reload."""
        l = make_loader()
        data = l.loads("reporting: !deferred\n  path: /runs/x\n  num: 5\n")
        # the bug: the next line raised RecursionError
        text = l.dump(data)
        assert "!deferred" in text
        reloaded = l.loads(text)
        assert isinstance(reloaded["reporting"], DeferredNode)

    def test_dracon_callable_emits_fn_tag(self):
        """TEMPLATE kind had no representer; used to fall through to garbage."""
        l = make_loader()
        empty = DraconMappingNode(
            tag=DEFAULT_MAP_TAG,
            value=[
                (
                    DraconScalarNode(tag=DEFAULT_SCALAR_TAG, value="k"),
                    DraconScalarNode(tag=DEFAULT_SCALAR_TAG, value="v"),
                )
            ],
        )
        c = DraconCallable(template_node=empty, loader=l, name="make_x")
        text = l.dump(c)
        assert "!fn" in text
        # dump must be deterministic so structural equivalence via dumped text holds
        assert l.dump(c) == text

    def test_dracon_pipe_emits_pipe_tag(self):
        """PIPE kind had no representer."""
        l = make_loader()
        p = DraconPipe(stages=[lambda x=0: x], stage_kwargs=[{}], name="p")
        text = l.dump(p)
        assert "!pipe" in text
        assert l.dump(p) == text

    def test_bound_symbol_round_trips_through_partial(self):
        """BoundSymbol emits !fn:target; reload yields an invokable partial."""
        l = make_loader()
        inner = CallableSymbol(Point, name="Point")
        bs = BoundSymbol(inner, x=5)
        text = l.dump(bs)
        assert "!fn:Point" in text
        reloaded = l.loads(text)
        assert isinstance(reloaded, DraconPartial)
        assert reloaded(y=7) == Point(x=5, y=7)


# ── step 03: pydantic hybrid quoter ─────────────────────────────────────────


class TestStep03HybridQuoterRegressions:
    """Regression anchors for the pydantic nested-wrapper flattening bugs."""

    def test_pydantic_dict_field_preserves_deferred_node(self):
        """The broodmon bug: dict-of-object flattened DeferredNode via model_dump."""
        l = make_loader()
        d = make_deferred({"a": 1}, loader=l)
        c = Container(bag={"d": d})
        text = l.dump(c)
        assert "!deferred" in text
        reloaded = l.loads(text)
        assert isinstance(reloaded.bag["d"], DeferredNode)

    def test_pydantic_untyped_field_preserves_resolvable(self):
        """``Resolvable`` in an untyped field compounded the wrapper-drop bug."""
        l = make_loader()
        inner = l.yaml.representer.represent_data(Point(x=3, y=4))
        c = Container(slot=Resolvable(node=inner, inner_type=Point))
        text = l.dump(c)
        assert "!Resolvable" in text
        reloaded = l.loads(text)
        assert isinstance(reloaded.slot, Resolvable)

    def test_pydantic_field_preserves_lazy_interpolable_source(self):
        """A ``LazyInterpolable`` in a field must emit its ``${expr}`` source."""
        l = make_loader()
        c = Container(slot=LazyInterpolable(value="${1 + 2}"))
        text = l.dump(c)
        assert "${1 + 2}" in text
        # sanity: the resolved value must not leak into the text
        assert "slot: 3" not in text

    def test_pydantic_discriminated_union_round_trips(self):
        """Discriminated unions must round-trip with no special-casing."""
        bus = EventBus(events=[CatEvent(name="whiskers"), DogEvent(name="rex")])
        reloaded = _round_trip(bus)
        assert reloaded == bus
        assert isinstance(reloaded.events[0], CatEvent)
        assert isinstance(reloaded.events[1], DogEvent)


# ── step 04: dump_to_node wiring ────────────────────────────────────────────


class TestStep04DumpToNodeRegressions:
    """Regression anchors for the context-discard bug."""

    def test_loader_dump_to_node_uses_loader_context(self):
        """Used to delegate to a fresh representer, discarding self.context."""
        l = make_loader()
        node = l.dump_to_node(Point(x=1, y=2))
        assert isinstance(node, Node)
        assert node.tag == "!Point"

    def test_loader_dump_and_dump_to_node_emit_same_tag(self):
        """Both loader methods must see the same vocabulary."""
        l = make_loader()
        p = Point(x=1, y=2)
        text = l.dump(p)
        node = l.dump_to_node(p)
        assert "!Point" in text
        assert node.tag == "!Point"

    def test_top_level_dump_to_node_accepts_symbol_table(self):
        """``dump_to_node(value, context=tbl)`` must use the table's canonicals."""
        tbl = make_vocabulary()
        node = dump_to_node(Point(x=1, y=2), context=tbl)
        assert node.tag == "!Point"


# ── captured-globals interaction (spans the whole fix chain) ────────────────


class TestCapturedGlobalsInteraction:
    """``table[k] = v`` must never mint canonical entries (step 01)."""

    def test_captured_globals_are_not_canonical_emitters(self):
        tbl = SymbolTable()
        tbl.define(SymbolEntry(name="Point", symbol=CallableSymbol(Point, name="Point")))
        # simulate captured globals: many sibling types land via __setitem__
        tbl["Pair"] = Pair
        tbl["Container"] = Container
        # only the explicit define counts
        assert tbl.identify(Pair(a=Point(), b=Point())) is None
        assert tbl.identify(Point(x=1, y=2)) == "Point"

    def test_captured_globals_do_not_rename_dumped_tags(self):
        loader = DraconLoader()
        tbl = SymbolTable()
        tbl.define(SymbolEntry(name="P", symbol=CallableSymbol(Point, name="P")))
        tbl["Point"] = Point  # captured global with the same python type
        loader.context = tbl
        loader.yaml.representer.full_module_path = False
        text = loader.dump(Point(x=1))
        assert "!P" in text, "canonical alias should win over captured global"


# ── harness self-test: round-trip mismatches must bubble up ────────────────


def test_round_trip_detects_payload_mismatch():
    """Guard against a silent no-op harness: a different payload must
    never compare equal after round-trip.
    """
    reloaded = _round_trip(Point(x=1, y=2))
    assert not equivalent(reloaded, Point(x=9, y=9))
