# Progress events

Dracon emits per-span progress events during construction and lazy `${...}` resolution when a subscriber is active. When no subscriber is bound, the cost is one contextvar read per construction — effectively free.

A subscriber is just `Callable[[Event], None]`. There is no class to subclass, no protocol to implement. Combinators (`tee`, `min_duration`, `name_filter`) are plain functions that wrap a subscriber and return another subscriber.

For a walkthrough, see the [Observing Progress](../guides/observing-progress.md) guide.

## Event types

Both event types are plain Pydantic models so they round-trip cleanly through `dump_line` / `loads_line` and serialize as JSON.

### `StepStart`

| field        | type                | meaning                              |
| ------------ | ------------------- | ------------------------------------ |
| `id`         | `int`               | per-process monotonic span id        |
| `parent_id`  | `int \| None`       | enclosing span's id, `None` at root  |
| `name`       | `str`               | human-readable label                 |
| `started_at` | `float`             | `time.monotonic()` at entry          |
| `meta`       | `dict[str, Any]`    | free-form metadata passed to `step`  |

### `StepEnd`

| field      | type          | meaning                            |
| ---------- | ------------- | ---------------------------------- |
| `id`       | `int`         | matches the corresponding `StepStart` |
| `ended_at` | `float`       | `time.monotonic()` at exit         |
| `duration` | `float`       | `ended_at - started_at`            |
| `error`    | `str \| None` | `"ExcName: msg"` if the span raised |

## Core API

```python
from dracon import (
    StepStart, StepEnd, Event, Subscriber,
    step, use_subscriber, subscriber,
    each, tee, min_duration, name_filter,
    jsonl_writer, read_jsonl, replay,
)
```

### `use_subscriber(sub)`

Context manager that installs `sub` as the active subscriber for the duration of the block. `sub` can be `None` to suppress events inside a region.

```python
with dracon.use_subscriber(print):
    dracon.load("config.yaml")
```

### `step(name, **meta)`

Context manager that opens a named span. The `parent_id` is derived automatically from any enclosing `step()`. Yields the span id (or `None` if no subscriber is active).

```python
with dracon.step("loading dataset", path=p):
    df = pd.read_parquet(p)
```

When no subscriber is active, `step()` short-circuits to a no-op.

### `each(name, items)`

Iterator wrapper that opens one span per item, labeled `name i/n` when `items` has `__len__`, else `name i`.

```python
for net in dracon.each("predicting batch", networks):
    yield model.predict(net)
```

### `subscriber()`

Returns the currently-installed subscriber, or `None`.

## Combinators

Each takes a subscriber and returns a subscriber. Composition is function composition.

### `tee(*subs)`

Fans every event out to multiple subscribers. `None` entries are ignored, so conditional inclusion is a one-liner:

```python
pipeline = dracon.tee(tui_sub, jsonl_sub, debug_sub if verbose else None)
```

### `min_duration(seconds, sub)`

Buffers each `StepStart` until its matching `StepEnd` arrives, then forwards both only if the duration exceeds the threshold. Spans that ended with an error are always forwarded regardless of duration.

```python
pipeline = dracon.min_duration(0.02, sub)   # drop everything under 20ms
```

### `name_filter(pred, sub)`

Drops spans whose name fails the predicate (both `StepStart` and matching `StepEnd`).

```python
pipeline = dracon.name_filter(lambda n: not n.startswith("resolve "), sub)
```

## JSONL persistence

### `jsonl_writer(fh)`

Returns a subscriber that writes one JSON object per event line to `fh` and flushes after each.

```python
with open("run.jsonl", "w") as fh:
    with dracon.use_subscriber(dracon.jsonl_writer(fh)):
        dracon.load("config.yaml")
```

### `read_jsonl(fh)`

Yields `Event` instances from a file produced by `jsonl_writer`. Discriminates `StepStart` vs `StepEnd` by the presence of the `duration` field.

### `replay(events, sub)`

Sends each event in `events` to `sub`. Useful for re-rendering a saved run through a different visualizer.

```python
with open("run.jsonl") as fh:
    dracon.replay(dracon.read_jsonl(fh), my_tree_printer())
```

## Auto-instrumentation

Two sites in dracon emit spans automatically when a subscriber is bound:

- `Draconstructor.construct_object` emits `construct {tag}` for every user-facing tag. Skipped tags: `!Type`, `!Ref`, `!raw`, `!noconstruct`, `!unset`, `!__py__`, and YAML core (`!!str`, `!!int`, etc.).
- `LazyInterpolable.resolve` emits `resolve {expr}` for each `${...}` evaluation.

The lazy-resolve span is the noisiest source — a single `dracon.load()` can produce thousands. Filter it out with `name_filter` or drop sub-millisecond entries with `min_duration` if you don't want it in your output.

There are no `progress=` knobs on `DraconLoader`. All filtering, fan-out, and persistence is composed on the subscriber side.

## Subscriber lifetime and threads

The active subscriber lives in a `ContextVar`, so it propagates correctly into `asyncio.create_task` and `loop.run_in_executor` but does **not** propagate into raw `threading.Thread` targets. If you need it inside a worker thread, capture the current context and run the target inside it:

```python
import contextvars, threading
ctx = contextvars.copy_context()
threading.Thread(target=ctx.run, args=(worker, ...)).start()
```

## Exception handling

If user code raises inside `with step(...)`, the `StepEnd` is still emitted with `error` populated (`"ExcName: message"`), then the exception re-raises. Subscribers see a balanced start/end stream even in failure paths.

## Round-trip through `dump_line`

Because `StepStart` and `StepEnd` are plain Pydantic, they round-trip through dracon's line-framed wire format too:

```python
from dracon import dump_line, loads_line, StepStart, StepEnd

vocab = {"StepStart": StepStart, "StepEnd": StepEnd}
wire = dump_line(event, context=vocab)
event_back = loads_line(wire, context=vocab)
```

For most cases `jsonl_writer` / `read_jsonl` is the simpler choice — use `dump_line` only when you need a unified wire format alongside other dracon documents.
