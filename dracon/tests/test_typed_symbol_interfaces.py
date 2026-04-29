# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Tests: typed symbol interfaces.

Covers:
- Python callable annotations preserved in ParamSpec
- Return annotations on InterfaceSpec
- BoundSymbol/DraconPipe propagate annotations on remaining params
- !require:Type / !set_default:Type / !returns:Type in !fn templates
- Same forms in !deferred
- SymbolTable.to_json determinism and JSON safety
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from dracon.loader import DraconLoader
from dracon.symbols import (
    BoundSymbol, CallableSymbol, InterfaceSpec, MISSING, ParamSpec,
    SymbolKind, auto_symbol,
)
from dracon.symbol_table import SymbolEntry, SymbolTable


@dataclass
class Event:
    name: str


@dataclass
class Gate:
    name: str


@dataclass
class PlotData:
    rows: int


def compute_plot(events: list[Event], gate: Gate) -> PlotData:
    return PlotData(rows=len(events))


def add(x: int, y: int = 1) -> int:
    return x + y


def untyped(x, y=1):
    return x + y


# ── Python callables ────────────────────────────────────────────────────────


class TestCallableAnnotations:
    def test_param_annotations_captured(self):
        sym = CallableSymbol(compute_plot, name="compute_plot")
        iface = sym.interface()
        params = {p.name: p for p in iface.params}
        assert params["events"].annotation == list[Event]
        assert params["events"].annotation_name == "list[Event]"
        assert params["gate"].annotation is Gate
        assert "Gate" in (params["gate"].annotation_name or "")

    def test_return_annotation_captured(self):
        sym = CallableSymbol(compute_plot, name="compute_plot")
        iface = sym.interface()
        assert iface.return_annotation is PlotData
        assert "PlotData" in (iface.return_annotation_name or "")

    def test_default_and_required_unchanged(self):
        sym = CallableSymbol(add)
        iface = sym.interface()
        params = {p.name: p for p in iface.params}
        assert params["x"].required is True
        assert params["x"].default is MISSING
        assert params["y"].required is False
        assert params["y"].default == 1
        assert params["x"].annotation_name == "int"
        assert params["y"].annotation_name == "int"

    def test_untyped_callable_yields_missing(self):
        sym = CallableSymbol(untyped)
        iface = sym.interface()
        params = {p.name: p for p in iface.params}
        assert params["x"].annotation is MISSING
        assert params["x"].annotation_name is None
        assert iface.return_annotation is MISSING
        assert iface.return_annotation_name is None


# ── BoundSymbol / DraconPipe propagation ────────────────────────────────────


class TestPropagation:
    def test_bound_symbol_keeps_annotations(self):
        bound = CallableSymbol(compute_plot).bind(gate=Gate(name="g1"))
        iface = bound.interface()
        params = {p.name: p for p in iface.params}
        assert "events" in params
        assert "gate" not in params
        assert params["events"].annotation == list[Event]
        assert iface.return_annotation is PlotData

    def test_pipe_propagates_annotations(self):
        loader = DraconLoader(context={"add": add})
        cfg = loader.loads(
            """
            !define p: !pipe
              - add
            pipe_ref: ${p}
            """
        )
        cfg.resolve_all_lazy()
        iface = cfg["pipe_ref"].interface()
        params = {p.name: p for p in iface.params}
        assert params["x"].annotation_name == "int"
        assert iface.return_annotation_name == "int"


# ── YAML !fn templates ─────────────────────────────────────────────────────


class TestTemplateAnnotations:
    def test_typed_require_in_fn(self):
        loader = DraconLoader(context={"Event": Event, "Gate": Gate, "PlotData": PlotData})
        cfg = loader.loads(
            """
            !define MakePlot: !fn
              !require:list[Event] events: "events to plot"
              !require:Gate gate: "active gate"
              !returns:PlotData _:
              kind: derive
            tmpl: ${MakePlot}
            """
        )
        cfg.resolve_all_lazy()
        iface = cfg["tmpl"].interface()
        assert iface.kind == SymbolKind.TEMPLATE
        params = {p.name: p for p in iface.params}
        assert params["events"].annotation == list[Event]
        assert params["events"].annotation_name == "list[Event]"
        assert params["events"].docs == "events to plot"
        # bare type name resolves through scope
        assert params["gate"].annotation is Gate
        assert params["gate"].annotation_name == "Gate"
        assert iface.return_annotation_name == "PlotData"
        assert iface.return_annotation is PlotData

    def test_typed_require_can_share_name_with_output_key(self):
        loader = DraconLoader(context={"Event": Event})
        cfg = loader.loads(
            """
            !define Echo: !fn
              !require:list[Event] events: "events"
              !require:Event event: "event"
              event: ${event}
            tmpl: ${Echo}
            """
        )
        cfg.resolve_all_lazy()
        params = {p.name: p for p in cfg["tmpl"].interface().params}
        assert params["events"].annotation == list[Event]
        assert params["event"].annotation is Event
        event = Event("clicked")
        assert cfg["tmpl"](events=[], event=event)["event"] is event

    def test_typed_set_default(self):
        loader = DraconLoader(context={"Gate": Gate})
        cfg = loader.loads(
            """
            !define mk: !fn
              !set_default:Gate gate: "default-gate"
              ok: 1
            tmpl: ${mk}
            """
        )
        cfg.resolve_all_lazy()
        iface = cfg["tmpl"].interface()
        params = {p.name: p for p in iface.params}
        assert params["gate"].required is False
        assert params["gate"].annotation_name == "Gate"
        assert params["gate"].annotation is Gate

    def test_untyped_require_still_works(self):
        loader = DraconLoader()
        cfg = loader.loads(
            """
            !define f: !fn
              !require x: "an x"
              !set_default y: 2
              v: ${x + y}
            tmpl: ${f}
            """
        )
        cfg.resolve_all_lazy()
        iface = cfg["tmpl"].interface()
        params = {p.name: p for p in iface.params}
        assert params["x"].required and params["x"].annotation_name is None
        assert not params["y"].required and params["y"].annotation_name is None

    def test_set_default_primitive_still_coerces(self):
        """!set_default:int must both annotate AND coerce the default value."""
        loader = DraconLoader()
        cfg = loader.loads(
            """
            !define mk: !fn
              !set_default:int port: "8080"
              !fn :
                p: ${port}
            tmpl: ${mk}
            default_port: ${mk()}
            """
        )
        cfg.resolve_all_lazy()
        # default value coerces from "8080" string to int via target_type=int
        assert cfg["default_port"]["p"] == 8080
        assert isinstance(cfg["default_port"]["p"], int)
        iface = cfg["tmpl"].interface()
        port_param = next(p for p in iface.params if p.name == "port")
        assert port_param.annotation_name == "int"

    def test_returns_value_form(self):
        """!returns _: TypeName form (type in value node, not in tag)."""
        loader = DraconLoader(context={"PlotData": PlotData})
        cfg = loader.loads(
            """
            !define mk: !fn
              !returns _: PlotData
              !fn :
                rows: 7
            tmpl: ${mk}
            out: ${mk()}
            """
        )
        cfg.resolve_all_lazy()
        iface = cfg["tmpl"].interface()
        assert iface.return_annotation_name == "PlotData"
        assert iface.return_annotation is PlotData
        # the marker is stripped — body still constructs cleanly
        assert cfg["out"]["rows"] == 7

    def test_returns_marker_removed_at_runtime(self):
        """!returns must not leak into the constructed mapping."""
        loader = DraconLoader(context={"PlotData": PlotData})
        cfg = loader.loads(
            """
            !define mk: !fn
              !returns:PlotData _:
              !fn :
                rows: 3
            out: ${mk()}
            """
        )
        cfg.resolve_all_lazy()
        # the !returns marker is stripped; remaining body is the rows mapping
        assert cfg["out"]["rows"] == 3


# ── !deferred ──────────────────────────────────────────────────────────────


class TestDeferredAnnotations:
    def test_typed_require_in_deferred(self):
        loader = DraconLoader(context={"Event": Event, "Gate": Gate, "PlotData": PlotData})
        cfg = loader.loads(
            """
            payload: !deferred
              !require:list[Event] events: "events"
              !require:Gate gate: "gate"
              !returns:PlotData _:
              kind: payload
            """
        )
        deferred = cfg["payload"]
        iface = deferred.interface()
        assert iface.kind == SymbolKind.DEFERRED
        params = {p.name: p for p in iface.params}
        assert params["events"].annotation_name == "list[Event]"
        assert params["gate"].annotation_name == "Gate"
        assert params["gate"].annotation is Gate
        assert iface.return_annotation_name == "PlotData"


# ── JSON output ────────────────────────────────────────────────────────────


class TestJsonOutput:
    def _build_table(self) -> SymbolTable:
        table = SymbolTable()
        table.define(SymbolEntry(name="compute_plot", symbol=CallableSymbol(compute_plot, name="compute_plot")))
        table.define(SymbolEntry(name="Gate", symbol=auto_symbol(Gate, name="Gate")))
        table.define(SymbolEntry(name="add", symbol=CallableSymbol(add, name="add")))
        return table

    def test_to_json_carries_annotations(self):
        table = self._build_table()
        data = table.to_json()
        cp = data["compute_plot"]
        assert cp["returns"] == cp["returns"]  # present
        assert cp["returns"].endswith("PlotData") or cp["returns"] == "PlotData"
        params = {p["name"]: p for p in cp["params"]}
        assert "annotation" in params["events"]
        assert "Event" in params["events"]["annotation"]

    def test_to_json_is_deterministic_and_serializable(self):
        table = self._build_table()
        a = table.to_json()
        b = table.to_json()
        assert a == b
        # whole dict json-serializes
        s = json.dumps(a, sort_keys=True)
        assert "compute_plot" in s
        # ordering of top-level keys is sorted
        assert list(a.keys()) == sorted(a.keys())
