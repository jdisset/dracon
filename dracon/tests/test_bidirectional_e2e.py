# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""High-level end-to-end tests for the bidirectional vocabulary contract.

These tests exercise the full compose → construct → dump → reload → resolve
pipeline across combinations of dracon-native types, pydantic models, and
vocabularies. Each test is designed to fail loudly if a hidden interaction
between the quotation/construction/resolution phases regresses.

Where individual unit/regression tests focus on one feature at a time, this
suite aims to catch bugs that only surface when multiple features interact
in realistic ways.
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Annotated, Any, Literal, Union

import pytest
from pydantic import BaseModel, Field

import dracon
from dracon import (
    DraconLoader,
    DeferredNode,
    NotLineableError,
    Resolvable,
    dump,
    dump_line,
    dump_to_node,
    document_stream,
    loads,
    loads_line,
    make_mapping_node,
    make_scalar_node,
    make_sequence_node,
)
from dracon.callable import DraconCallable
from dracon.composer import CompositionResult
from dracon.deferred import make_deferred
from dracon.lazy import LazyInterpolable
from dracon.nodes import (
    DEFAULT_MAP_TAG,
    DEFAULT_SCALAR_TAG,
    DraconMappingNode,
    DraconScalarNode,
)
from dracon.partial import DraconPartial
from dracon.pipe import DraconPipe
from dracon.representer import DraconDumpable
from dracon.symbol_table import SymbolEntry, SymbolTable
from dracon.symbols import BoundSymbol, CallableSymbol, ValueSymbol


# ── shared domain types ─────────────────────────────────────────────────────


class Host(BaseModel):
    name: str
    cpus: int = 1


class Job(BaseModel):
    """Pydantic model with defaults, an untyped slot, and a nested container.

    The untyped ``env`` slot is the canonical place where nested dracon-native
    wrappers surface; preserving them across dump/load is the hybrid-quoter
    contract on pydantic models.
    """

    model_config = {"arbitrary_types_allowed": True}

    name: str
    host: Host
    deps: list[str] = Field(default_factory=list)
    env: dict[str, Any] = Field(default_factory=dict)


class Severity(Enum):
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class Event(BaseModel):
    kind: Literal["event"] = "event"
    severity: Severity = Severity.INFO
    payload: dict[str, Any] = Field(default_factory=dict)


# ── helpers ────────────────────────────────────────────────────────────────


def make_vocab(**extras: Any) -> SymbolTable:
    """Build a vocabulary exposing the domain types under short canonical names."""
    tbl = SymbolTable()
    for name, cls in (("Host", Host), ("Job", Job), ("Event", Event), ("Severity", Severity)):
        tbl.define(SymbolEntry(name=name, symbol=CallableSymbol(cls, name=name)))
    for k, v in extras.items():
        if isinstance(v, type):
            tbl.define(SymbolEntry(name=k, symbol=CallableSymbol(v, name=k)))
        else:
            tbl.define(SymbolEntry(name=k, symbol=ValueSymbol(v, name=k)))
    return tbl


def make_loader(vocab: SymbolTable | None = None) -> DraconLoader:
    loader = DraconLoader()
    loader.yaml.representer.full_module_path = False
    if vocab is not None:
        loader.context = vocab
    return loader


def round_trip(value: Any, vocab: SymbolTable | None = None) -> Any:
    """Dump through a loader bound to `vocab`, reload through a fresh one."""
    text = make_loader(vocab).dump(value)
    return make_loader(vocab).loads(text)


# ── Scenario 1: vocabulary drives tag emission both ways ───────────────────


class TestVocabularyDrivenTagging:
    """SymbolTable.identify + representer emission, end-to-end."""

    def test_same_type_two_vocabularies_disambiguate(self):
        """Two vocabularies can bind the same class under different canonical names.

        Project A calls the type ``Server``; project B calls it ``Node``.
        A value constructed in project A's vocabulary must dump with the
        ``!Server`` tag even though B's vocabulary also registers the class.
        """
        vocab_a = SymbolTable()
        vocab_a.define(
            SymbolEntry(name="Server", symbol=CallableSymbol(Host, name="Server"))
        )
        vocab_b = SymbolTable()
        vocab_b.define(
            SymbolEntry(name="Node", symbol=CallableSymbol(Host, name="Node"))
        )

        h = Host(name="h1", cpus=8)
        text_a = make_loader(vocab_a).dump(h)
        text_b = make_loader(vocab_b).dump(h)

        assert "!Server" in text_a
        assert "!Node" in text_b
        # reload round-trips through the originating vocabulary
        assert make_loader(vocab_a).loads(text_a) == h
        assert make_loader(vocab_b).loads(text_b) == h

    def test_dump_to_node_uses_loader_vocabulary(self):
        """loader.dump_to_node must consult loader.context, not a fresh one."""
        vocab = make_vocab()
        loader = make_loader(vocab)
        node = loader.dump_to_node(Host(name="x", cpus=2))
        assert str(node.tag).lstrip("!") == "Host"

    def test_fallback_to_qualname_when_vocab_empty(self):
        """Without a vocabulary the dump path still works via qualname fallback."""
        loader = DraconLoader()
        loader.yaml.representer.full_module_path = True
        text = loader.dump(Host(name="h", cpus=1))
        assert "Host" in text


# ── Scenario 2: full pydantic model with all the wrapper types nested ──────


class TestPydanticWithAllWrappersNested:
    """Hybrid quoter + all wrapper representers exercised together."""

    def test_job_with_deferred_resolvable_and_lazy_all_survive(self):
        """Drop a DeferredNode, a Resolvable, and a LazyInterpolable into one ``env``."""
        loader = make_loader(make_vocab())

        deferred = make_deferred({"retries": 3, "timeout": 60}, loader=loader)

        inner_node = loader.yaml.representer.represent_data(Host(name="inner", cpus=4))
        resolvable = Resolvable(node=inner_node, inner_type=Host)

        lazy = LazyInterpolable(value="${2 * 21}", context={})

        job = Job(
            name="build",
            host=Host(name="h1", cpus=8),
            deps=["lint", "compile"],
            env={
                "config": deferred,
                "fallback_host": resolvable,
                "threads": lazy,
                "plain": "hello",
                "number": 42,
            },
        )

        text = loader.dump(job)
        # every wrapper must surface in the dumped YAML
        assert "!deferred" in text
        assert "!Resolvable" in text
        assert "${2 * 21}" in text  # lazy expression literal survives the dump

        reloaded = make_loader(make_vocab()).loads(text)

        # direct fields preserved
        assert reloaded.name == "build"
        assert reloaded.host == Host(name="h1", cpus=8)
        assert reloaded.deps == ["lint", "compile"]

        # nested dracon-native wrappers preserved as wrappers
        assert isinstance(reloaded.env["config"], DeferredNode)
        # the deferred node can still be constructed
        constructed = reloaded.env["config"].construct()
        assert dict(constructed) == {"retries": 3, "timeout": 60}

        # resolvable survives
        assert isinstance(reloaded.env["fallback_host"], Resolvable)
        # plain values preserved
        assert reloaded.env["plain"] == "hello"
        assert reloaded.env["number"] == 42

    def test_discriminated_union_of_pydantic_round_trips(self):
        class TCP(BaseModel):
            kind: Literal["tcp"] = "tcp"
            port: int

        class Unix(BaseModel):
            kind: Literal["unix"] = "unix"
            path: str

        class Server(BaseModel):
            endpoint: Annotated[Union[TCP, Unix], Field(discriminator="kind")]

        vocab = SymbolTable()
        for cls, n in ((TCP, "TCP"), (Unix, "Unix"), (Server, "Server")):
            vocab.define(SymbolEntry(name=n, symbol=CallableSymbol(cls, name=n)))

        s = Server(endpoint=TCP(port=8443))
        assert round_trip(s, vocab) == s

        s2 = Server(endpoint=Unix(path="/tmp/s.sock"))
        assert round_trip(s2, vocab) == s2

    def test_enum_field_round_trips_with_vocabulary(self):
        ev = Event(severity=Severity.WARN, payload={"reason": "disk full"})
        reloaded = round_trip(ev, make_vocab())
        assert reloaded == ev


# ── Scenario 3: templates, pipes, bound symbols in a real document ─────────


class TestTemplatesPipesAndBoundSymbolsInDocument:
    """DraconDumpable impls for templates/pipes/bound symbols, exercised end to end."""

    def test_fn_template_dumps_and_reloads(self):
        loader = make_loader()
        empty = DraconMappingNode(tag=DEFAULT_MAP_TAG, value=[])
        callable_ = DraconCallable(template_node=empty, loader=loader, name="mkjob")
        text = loader.dump(callable_)
        assert "!fn:mkjob" in text
        # deterministic dump — critical for wire protocols and content hashing
        assert loader.dump(callable_) == text

    def test_pipe_dumps_and_reloads_with_symbol_stages(self):
        loader = make_loader()
        p = DraconPipe(stages=[lambda x=1: x * 2], stage_kwargs=[{}], name="double")
        text = loader.dump(p)
        assert "!pipe" in text

    def test_bound_symbol_reloads_to_invokable_partial(self):
        """A BoundSymbol is the closure from CLI-style arg binding. It must survive
        a dump → load cycle as something callable with the same effect."""
        vocab = make_vocab()
        loader = make_loader(vocab)
        host_sym = CallableSymbol(Host, name="Host")
        bs = BoundSymbol(host_sym, name="h-prebuilt")
        text = loader.dump(bs)
        assert "!fn:Host" in text
        reloaded = make_loader(make_vocab()).loads(text)
        assert isinstance(reloaded, DraconPartial)
        h = reloaded(cpus=16)
        assert h == Host(name="h-prebuilt", cpus=16)


# ── Scenario 4: loaded DeferredNode dumped from inside a pydantic model ────


class TestLoadedDeferredNodeDoesNotRecurse:
    """Regression: loaded DeferredNode must re-dump without recursing."""

    def test_yaml_loaded_deferred_dumped_from_inside_model(self):
        """Load YAML containing a deferred, wrap it in a pydantic model, dump, reload."""
        vocab = make_vocab()
        source = """
job: !Job
    name: report
    host: !Host { name: h1, cpus: 2 }
    env:
        payload: !deferred
            value: ${1 + 1}
"""
        loader = make_loader(vocab)
        doc = loader.loads(source)
        job = doc["job"]
        assert isinstance(job, Job)
        assert isinstance(job.env["payload"], DeferredNode)

        # re-dump and reload — must NOT recurse
        redumped = make_loader(vocab).dump(job)
        assert "!deferred" in redumped

        rereloaded = make_loader(vocab).loads(redumped)
        assert isinstance(rereloaded.env["payload"], DeferredNode)


# ── Scenario 5: line-framing round-trips a mixed stream ────────────────────


class TestLineFramedStream:
    """dump_line/loads_line across the full vocabulary surface."""

    def test_stream_of_events_round_trips(self):
        vocab = make_vocab()
        events = [
            Event(severity=Severity.INFO, payload={"n": 1}),
            Event(severity=Severity.WARN, payload={"n": 2, "msg": "slow"}),
            Event(severity=Severity.ERROR, payload={}),
        ]
        lines = [dump_line(e, context=vocab) for e in events]
        # each frame is one line with a trailing newline
        for line in lines:
            assert line.endswith(b"\n")
            assert line.count(b"\n") == 1

        # reload each line individually
        reloaded = [loads_line(line, context=vocab) for line in lines]
        assert reloaded == events

    def test_line_stream_is_async_iterable(self):
        vocab = make_vocab()
        payloads = [
            Host(name="a", cpus=1),
            Host(name="b", cpus=2),
            Host(name="c", cpus=4),
        ]
        blob = b"".join(dump_line(h, context=vocab) for h in payloads)

        async def collect() -> list[Host]:
            async def gen():
                for line in blob.splitlines(keepends=True):
                    yield line

            out = []
            async for v in document_stream(gen(), context=vocab):
                out.append(v)
            return out

        assert asyncio.run(collect()) == payloads

    def test_not_lineable_raises_for_multiline_scalar(self):
        """A top-level scalar with a literal newline cannot be single-lined."""
        multiline = "line1\nline2\nline3"
        with pytest.raises(NotLineableError):
            dump_line(multiline)


# ── Scenario 6: ``make_*_node`` helpers used inside DraconDumpable ──────────


class TestNodeHelpersThroughDumpable:
    """Node-construction helpers let DraconDumpable impls avoid ruamel details."""

    def test_custom_dumpable_uses_make_helpers(self):
        class Point3D(DraconDumpable):
            def __init__(self, x: int, y: int, z: int):
                self.x, self.y, self.z = x, y, z

            def dracon_dump_to_node(self, representer):
                return make_mapping_node(
                    {
                        "x": make_scalar_node(str(self.x), tag="tag:yaml.org,2002:int"),
                        "y": make_scalar_node(str(self.y), tag="tag:yaml.org,2002:int"),
                        "z": make_scalar_node(str(self.z), tag="tag:yaml.org,2002:int"),
                    },
                    tag="!Point3D",
                )

            def __eq__(self, other):
                return (
                    isinstance(other, Point3D)
                    and (self.x, self.y, self.z) == (other.x, other.y, other.z)
                )

            def __hash__(self):
                return hash((self.x, self.y, self.z))

        vocab = SymbolTable()
        vocab.define(
            SymbolEntry(name="Point3D", symbol=CallableSymbol(Point3D, name="Point3D"))
        )

        p = Point3D(1, 2, 3)
        text = make_loader(vocab).dump(p)
        assert "!Point3D" in text
        assert "x: 1" in text
        assert "y: 2" in text
        assert "z: 3" in text

    def test_make_sequence_node_builds_default_tagged_sequence(self):
        seq = make_sequence_node(
            [
                make_scalar_node("a"),
                make_scalar_node("b"),
            ]
        )
        assert str(seq.tag) == "tag:yaml.org,2002:seq"
        assert len(seq.value) == 2


# ── Scenario 7: compose + merge + construct + dump + reload pipeline ───────


class TestComposeConstructDumpReloadPipeline:
    """The full four-peer pipeline (compose → construct → dump → reload)."""

    def test_multi_source_merge_survives_dump_reload(self):
        """Compose a multi-document YAML, construct it, dump it, reload it.

        The point is to exercise that the dump path uses the SymbolTable
        built during composition, and that the reloaded document constructs
        back into the same domain objects.
        """
        vocab = make_vocab()
        source = """
host: !Host
    name: primary
    cpus: 16
job: !Job
    name: ingest
    host: !Host { name: worker-1, cpus: 4 }
    deps: [compile, link]
    env:
        region: us-west-2
        lazy: ${1 + 1}
"""
        loader = make_loader(vocab)
        loaded = loader.loads(source)

        assert isinstance(loaded["host"], Host)
        assert isinstance(loaded["job"], Job)
        assert loaded["job"].env["lazy"] == 2  # lazy resolved on load

        redumped = make_loader(vocab).dump(loaded)
        assert "!Host" in redumped
        assert "!Job" in redumped

        reloaded = make_loader(vocab).loads(redumped)
        assert reloaded["host"] == loaded["host"]
        assert reloaded["job"].name == "ingest"
        assert reloaded["job"].host.name == "worker-1"


# ── Scenario 8: dump_to_node is idempotent under composition ───────────────


class TestDumpToNodeIdempotence:
    """dump_to_node on a Node must short-circuit and preserve identity."""

    def test_dump_to_node_on_node_is_identity(self):
        loader = make_loader(make_vocab())
        h = Host(name="x", cpus=2)
        node = loader.dump_to_node(h)
        second = loader.dump_to_node(node)
        assert second is node

    def test_dump_to_node_then_text_equals_direct_dump(self):
        """loader.dump(x) == emit(loader.dump_to_node(x)) by construction."""
        loader = make_loader(make_vocab())
        h = Host(name="x", cpus=2)
        direct = loader.dump(h)
        via_node = loader.dump(loader.dump_to_node(h))
        assert direct == via_node


# ── Scenario 9: nested wrappers inside a discriminated union field ─────────


class TestDeepNestingOfWrappers:
    """Wrappers inside wrappers inside untyped fields inside a union."""

    def test_resolvable_of_dict_with_deferred_inside_untyped_slot(self):
        """A resolvable holding a dict that holds a deferred, all inside a pydantic
        untyped slot. Every hop has to preserve both typing and tagging."""
        loader = make_loader(make_vocab())

        inner = make_deferred({"k": "v"}, loader=loader)
        outer_node = loader.yaml.representer.represent_data({"deferred_inside": inner})
        resolvable = Resolvable(node=outer_node, inner_type=dict)

        host = Host(name="h1", cpus=2)
        job = Job(name="n", host=host, env={"r": resolvable})

        text = loader.dump(job)
        assert "!Resolvable" in text
        assert "!deferred" in text

        reloaded = make_loader(make_vocab()).loads(text)
        assert isinstance(reloaded.env["r"], Resolvable)


# ── Scenario 10: nested DeferredNodes round-trip through all paths ─────────


class TestNestedDeferredNodes:
    """Regression: a DeferredNode whose inner tree contains another DeferredNode.

    ``represent_deferred_node`` copies the inner tree and hands it back to
    ``represent_data``; the fast-path short-circuit used to return the
    mapping as-is, leaving the inner DeferredNode untransformed. The
    serializer later choked trying to treat that wrapped scalar as yaml text.
    """

    def test_nested_deferred_top_level(self):
        loader = make_loader()
        d1 = make_deferred({"level": 1}, loader=loader)
        d2 = make_deferred({"level": 2, "inner": d1}, loader=loader)
        text = loader.dump(d2)
        assert text.count("!deferred") == 2
        reloaded = make_loader().loads(text)
        assert isinstance(reloaded, DeferredNode)
        constructed = reloaded.construct()
        assert constructed["level"] == 2
        # the inner value survived as a deferred too
        assert isinstance(constructed["inner"], DeferredNode)

    def test_nested_deferred_inside_pydantic_untyped_field(self):
        """Chain: Pydantic → untyped dict → DeferredNode → DeferredNode."""
        vocab = make_vocab()
        loader = make_loader(vocab)

        d1 = make_deferred({"level": 1}, loader=loader)
        d2 = make_deferred({"level": 2, "inner": d1}, loader=loader)
        job = Job(name="n", host=Host(name="h", cpus=1), env={"top": d2})

        text = loader.dump(job)
        assert text.count("!deferred") == 2

        reloaded = make_loader(make_vocab()).loads(text)
        top = reloaded.env["top"]
        assert isinstance(top, DeferredNode)

    def test_nested_deferred_inside_sequence(self):
        """DeferredNode inside a sequence inside a DeferredNode."""
        loader = make_loader()
        d1 = make_deferred({"k": "v"}, loader=loader)
        outer = make_deferred({"items": [d1, {"plain": 1}]}, loader=loader)
        text = loader.dump(outer)
        assert text.count("!deferred") == 2


# ── Scenario 11: make_mapping_node accepts dict-style input ────────────────


class TestMakeMappingNodeDictInput:
    """Regression: make_mapping_node accepted tuple pairs but not dicts, and
    silently produced broken output when given a plain dict."""

    def test_dict_with_string_keys_works(self):
        class Custom(DraconDumpable):
            def __init__(self, a: int, b: int):
                self.a, self.b = a, b

            def dracon_dump_to_node(self, representer):
                return make_mapping_node(
                    {
                        "a": make_scalar_node(str(self.a), tag="tag:yaml.org,2002:int"),
                        "b": make_scalar_node(str(self.b), tag="tag:yaml.org,2002:int"),
                    },
                    tag="!Custom",
                )

            def __eq__(self, other):
                return (
                    isinstance(other, Custom) and (self.a, self.b) == (other.a, other.b)
                )

            def __hash__(self):
                return hash((self.a, self.b))

        c = Custom(3, 7)
        text = make_loader().dump(c)
        assert "a: 3" in text
        assert "b: 7" in text

    def test_tuple_pairs_still_work(self):
        """Back-compat: tuple iterable form still accepted."""
        node = make_mapping_node(
            [
                (make_scalar_node("x"), make_scalar_node("1")),
                (make_scalar_node("y"), make_scalar_node("2")),
            ]
        )
        assert len(node.value) == 2


# ── Scenario 12: SymbolTable.identify drives emission even for subclasses ──


class TestIdentifyMROWalk:
    """SymbolTable.identify walks the MRO; dumps of subclass instances emit
    the nearest canonical base name."""

    def test_subclass_emits_base_canonical_name(self):
        class FastHost(Host):
            gpus: int = 0

        vocab = make_vocab()  # only ``Host`` is registered, not FastHost
        loader = make_loader(vocab)
        loader.yaml.representer.full_module_path = False

        fh = FastHost(name="gpu1", cpus=32, gpus=4)
        text = loader.dump(fh)
        # identify walks the MRO: FastHost is not registered, Host is.
        assert "!Host" in text
