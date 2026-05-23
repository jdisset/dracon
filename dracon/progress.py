# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

"""Live progress events for construction and resolution.

A subscriber is just ``Callable[[Event], None]``. Composition happens
via function decorators (`tee`, `min_duration`, `name_filter`) rather
than subclassing. Events are plain Pydantic models so they round-trip
through `dump_line` / `loads_line` for free.

    from dracon.progress import use_subscriber, step

    def show(e): print(e)

    with use_subscriber(show), step("load"):
        cfg = dracon.load("config.yaml")
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from itertools import count
from typing import Any, Callable, IO, Iterable, Iterator

from pydantic import BaseModel, Field


class StepStart(BaseModel):
    id: int
    parent_id: int | None = None
    name: str
    started_at: float
    meta: dict[str, Any] = Field(default_factory=dict)


class StepEnd(BaseModel):
    id: int
    ended_at: float
    duration: float
    error: str | None = None


Event = StepStart | StepEnd
Subscriber = Callable[[Event], None]


_subscriber: ContextVar[Subscriber | None] = ContextVar("dracon_progress", default=None)
_active_id: ContextVar[int | None] = ContextVar("dracon_progress_parent", default=None)
_id_seq = count(1)


def subscriber() -> Subscriber | None:
    return _subscriber.get()


@contextmanager
def use_subscriber(sub: Subscriber | None) -> Iterator[Subscriber | None]:
    token = _subscriber.set(sub)
    try:
        yield sub
    finally:
        _subscriber.reset(token)


@contextmanager
def step(name: str, **meta: Any) -> Iterator[int | None]:
    sub = _subscriber.get()
    if sub is None:
        yield None
        return
    sid = next(_id_seq)
    parent = _active_id.get()
    t0 = time.monotonic()
    sub(StepStart(id=sid, parent_id=parent, name=name, started_at=t0, meta=meta))
    p_token = _active_id.set(sid)
    err: str | None = None
    try:
        yield sid
    except BaseException as e:
        err = f"{type(e).__name__}: {e}"
        raise
    finally:
        _active_id.reset(p_token)
        t1 = time.monotonic()
        sub(StepEnd(id=sid, ended_at=t1, duration=t1 - t0, error=err))


def each(name: str, items: Iterable[Any], total: int | None = None) -> Iterator[Any]:
    if total is None:
        try:
            total = len(items)  # type: ignore[arg-type]
        except TypeError:
            total = None
    for i, item in enumerate(items):
        label = f"{name} {i + 1}/{total}" if total else f"{name} {i + 1}"
        with step(label):
            yield item


def tee(*subs: Subscriber | None) -> Subscriber:
    active = [s for s in subs if s is not None]
    def fanout(e: Event) -> None:
        for s in active:
            s(e)
    return fanout


def min_duration(threshold: float, sub: Subscriber) -> Subscriber:
    """Drop spans shorter than ``threshold`` seconds (buffers StepStart until matching StepEnd)."""
    pending: dict[int, StepStart] = {}
    def wrap(e: Event) -> None:
        if isinstance(e, StepStart):
            pending[e.id] = e
            return
        start = pending.pop(e.id, None)
        if e.duration >= threshold or e.error is not None:
            if start is not None:
                sub(start)
            sub(e)
    return wrap


def name_filter(pred: Callable[[str], bool], sub: Subscriber) -> Subscriber:
    """Drop spans whose name fails ``pred``. Drops the matching StepEnd too."""
    dropped: set[int] = set()
    def wrap(e: Event) -> None:
        if isinstance(e, StepStart):
            if not pred(e.name):
                dropped.add(e.id)
                return
            sub(e)
        else:
            if e.id in dropped:
                dropped.discard(e.id)
                return
            sub(e)
    return wrap


def jsonl_writer(fh: IO[str]) -> Subscriber:
    def write(e: Event) -> None:
        fh.write(e.model_dump_json())
        fh.write("\n")
        fh.flush()
    return write


def read_jsonl(fh: IO[str]) -> Iterator[Event]:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        yield (StepEnd(**d) if "duration" in d else StepStart(**d))


def replay(events: Iterable[Event], sub: Subscriber) -> None:
    for e in events:
        sub(e)
