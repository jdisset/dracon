# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
"""Progress events: subscriber callable + auto-instrumented spans."""
import io
import pytest
from pydantic import BaseModel

import dracon
from dracon import loads, resolve_all_lazy
from dracon.progress import (
    StepStart, StepEnd, step, use_subscriber, subscriber,
    each, tee, min_duration, name_filter, jsonl_writer, read_jsonl, replay,
)


def _collect():
    out = []
    return out, out.append


def test_no_subscriber_is_noop():
    out, sink = _collect()
    with step("anything"):
        pass
    assert out == []
    assert subscriber() is None


def test_basic_step_emits_start_and_end():
    out, sink = _collect()
    with use_subscriber(sink):
        with step("work", k="v"):
            pass
    assert len(out) == 2
    assert isinstance(out[0], StepStart) and out[0].name == "work" and out[0].meta == {"k": "v"}
    assert isinstance(out[1], StepEnd) and out[1].id == out[0].id and out[1].duration >= 0
    assert out[1].error is None


def test_nested_spans_track_parent():
    out, sink = _collect()
    with use_subscriber(sink):
        with step("outer"):
            with step("inner"):
                pass
    starts = [e for e in out if isinstance(e, StepStart)]
    assert starts[0].parent_id is None
    assert starts[1].parent_id == starts[0].id


def test_exception_in_step_records_error_and_propagates():
    out, sink = _collect()
    with use_subscriber(sink):
        with pytest.raises(RuntimeError, match="boom"):
            with step("crashy"):
                raise RuntimeError("boom")
    end = [e for e in out if isinstance(e, StepEnd)][0]
    assert end.error and "RuntimeError" in end.error


def test_use_subscriber_is_scoped():
    out, sink = _collect()
    with use_subscriber(sink):
        with step("inside"):
            pass
    with step("outside"):
        pass
    names = [e.name for e in out if isinstance(e, StepStart)]
    assert names == ["inside"]


def test_each_emits_numbered_spans():
    out, sink = _collect()
    with use_subscriber(sink):
        for _ in each("batch", [1, 2, 3]):
            pass
    names = [e.name for e in out if isinstance(e, StepStart)]
    assert names == ["batch 1/3", "batch 2/3", "batch 3/3"]


def test_each_unsized_iterable():
    out, sink = _collect()
    with use_subscriber(sink):
        for _ in each("stream", iter([1, 2])):
            pass
    names = [e.name for e in out if isinstance(e, StepStart)]
    assert names == ["stream 1", "stream 2"]


def test_tee_fans_out():
    a_out, a = _collect()
    b_out, b = _collect()
    fan = tee(a, b)
    with use_subscriber(fan):
        with step("dup"):
            pass
    assert len(a_out) == 2 and len(b_out) == 2


def test_min_duration_drops_short_spans():
    out, sink = _collect()
    filt = min_duration(10.0, sink)  # impossibly long threshold
    with use_subscriber(filt):
        with step("fast"):
            pass
    assert out == []


def test_min_duration_keeps_errors():
    out, sink = _collect()
    filt = min_duration(10.0, sink)
    with use_subscriber(filt):
        with pytest.raises(RuntimeError):
            with step("fast_but_bad"):
                raise RuntimeError("x")
    assert len(out) == 2  # both start and end emitted because error != None


def test_name_filter_drops_matching():
    out, sink = _collect()
    filt = name_filter(lambda n: not n.startswith("noise"), sink)
    with use_subscriber(filt):
        with step("noise A"):
            pass
        with step("signal"):
            pass
    names = [e.name for e in out if isinstance(e, StepStart)]
    assert names == ["signal"]


def test_jsonl_roundtrip():
    fh = io.StringIO()
    sink = jsonl_writer(fh)
    with use_subscriber(sink):
        with step("alpha", n=1):
            with step("beta"):
                pass
    fh.seek(0)
    events = list(read_jsonl(fh))
    assert [type(e).__name__ for e in events] == ["StepStart", "StepStart", "StepEnd", "StepEnd"]
    assert events[0].name == "alpha" and events[0].meta == {"n": 1}


def test_replay_feeds_subscriber():
    fh = io.StringIO()
    with use_subscriber(jsonl_writer(fh)):
        with step("a"):
            pass
    fh.seek(0)
    out, sink = _collect()
    replay(read_jsonl(fh), sink)
    assert len(out) == 2 and out[0].name == "a"


# --- auto-instrumentation: construction --------------------------------------


class _Thing(BaseModel):
    x: int


def test_construct_span_fires_for_user_tag():
    out, sink = _collect()
    with use_subscriber(sink):
        loads("v: !_Thing { x: 1 }", context={"_Thing": _Thing})
    names = [e.name for e in out if isinstance(e, StepStart)]
    assert any(n == "construct !_Thing" for n in names)


def test_construct_span_skips_internal_tags():
    out, sink = _collect()
    with use_subscriber(sink):
        loads("!define x: 1\nv: ${x}")
    names = [e.name for e in out if isinstance(e, StepStart)]
    # !!str, !!int etc must not appear
    assert all(not n.startswith("construct !!") for n in names)
    # internal markers must not appear
    for skipped in ("!noconstruct", "!unset", "!__py__", "!Type", "!Ref", "!raw"):
        assert all(skipped not in n for n in names)


def test_no_subscriber_does_not_emit_during_construction():
    # purely a sanity check that absence of subscriber is silent
    loads("v: !_Thing { x: 1 }", context={"_Thing": _Thing})
    assert subscriber() is None


# --- auto-instrumentation: lazy resolution -----------------------------------


def test_resolve_span_fires_for_interpolation():
    out, sink = _collect()
    cfg = loads("a: 1\nb: ${1 + 2}")
    with use_subscriber(sink):
        resolve_all_lazy(cfg)
    names = [e.name for e in out if isinstance(e, StepStart)]
    assert any(n.startswith("resolve ") for n in names)


# --- composition pipelines ---------------------------------------------------


def test_pipeline_min_duration_plus_tee():
    keep, ksink = _collect()
    all_, asink = _collect()
    pipeline = min_duration(0.0, tee(ksink, asink))  # 0.0 == keep everything
    with use_subscriber(pipeline):
        with step("x"):
            pass
    assert len(keep) == 2 and len(all_) == 2


def test_pipeline_name_filter_then_jsonl():
    fh = io.StringIO()
    pipeline = name_filter(lambda n: n != "drop", jsonl_writer(fh))
    with use_subscriber(pipeline):
        with step("keep"):
            pass
        with step("drop"):
            pass
    fh.seek(0)
    events = list(read_jsonl(fh))
    starts = [e for e in events if isinstance(e, StepStart)]
    assert [s.name for s in starts] == ["keep"]


def test_step_returns_id_when_subscriber_active():
    with use_subscriber(lambda e: None):
        with step("x") as sid:
            assert isinstance(sid, int)
    with step("y") as sid:
        assert sid is None  # no subscriber
