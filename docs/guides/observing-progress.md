# Observing Progress

Composition is usually fast. **Construction** (typed-tag instantiation) and **lazy resolution** (`${...}` evaluation) are the phases where dracon waits on real work — loading model pickles, querying databases, building indices. From a host program's perspective these phases are one opaque call.

Dracon emits typed events at both sites when a *subscriber* is bound, so a host can render live progress, write a JSONL log, or push spans into OpenTelemetry. When no subscriber is bound, the cost is one contextvar read per construction.

The API surface is small: a subscriber is just `Callable[[Event], None]`. There are no `Reporter` classes to subclass.

For the complete reference, see [Progress Events](../reference/progress-events.md).

## Tier 1 — see every event

The simplest subscriber is `print`:

```python
import dracon

with dracon.use_subscriber(print):
    cfg = dracon.load("config.yaml")
    dracon.resolve_all_lazy(cfg)
```

You'll see a flat stream of `StepStart` and `StepEnd` objects. Fine for poking around; not pretty.

## Tier 2 — render an indented tree

Each event carries `parent_id`, so a subscriber can derive nesting:

```python
def tree_printer():
    depth = {None: -1}
    starts = {}
    def sub(e):
        if isinstance(e, dracon.StepStart):
            depth[e.id] = depth[e.parent_id] + 1
            starts[e.id] = e
        else:
            d = depth.pop(e.id)
            name = starts.pop(e.id).name
            print(f"{'  ' * d}{name:40s} {e.duration*1000:7.1f} ms")
    return sub

with dracon.use_subscriber(tree_printer()):
    cfg = dracon.load("config.yaml")
```

Typical output for a job that loads a model and runs a few stages:

```
construct !DBSource                          51.3 ms
construct !NetworkModel                     254.2 ms
  read pickle                               201.0 ms
  build index                                51.3 ms
construct !NetworkPrediction                  3.1 ms
```

## Tier 3 — compose filters and persistence

Combinators (`tee`, `min_duration`, `name_filter`) are functions that take a subscriber and return a subscriber. Chain them like middleware:

```python
with open("/tmp/run.jsonl", "w") as fh:
    pipeline = dracon.min_duration(
        0.02,                                            # drop sub-20ms noise
        dracon.tee(
            tree_printer(),                              # live console
            dracon.jsonl_writer(fh),                     # log to disk
        ),
    )
    with dracon.use_subscriber(pipeline):
        cfg = dracon.load("config.yaml")
        dracon.resolve_all_lazy(cfg)
```

Lazy resolution can be the noisiest source. Filter it out:

```python
pipeline = dracon.name_filter(lambda n: not n.startswith("resolve "), sub)
```

## Tier 4 — your own spans in user code

The auto-instrumentation only sees the dracon side. Heavy work inside a Pydantic constructor or a `!fn` body is invisible unless you mark it. Use `dracon.step` and nesting is automatic:

```python
import time
from pydantic import BaseModel
import dracon

class NetworkModel(BaseModel):
    path: str

    def model_post_init(self, _):
        with dracon.step("read pickle", path=self.path):
            time.sleep(0.2)
        with dracon.step("build index"):
            time.sleep(0.05)
```

Because the active span lives in a `ContextVar`, the `read pickle` span automatically nests under whatever `construct !NetworkModel` span dracon opened — no plumbing.

For loops, `dracon.each(name, items)` opens a numbered span per item:

```python
for net in dracon.each("predicting batch", networks):
    yield model.predict(net)
```

Emits `predicting batch 1/12`, `predicting batch 2/12`, etc.

## Replaying a log

Anything `jsonl_writer` wrote can be re-rendered through any subscriber:

```python
with open("/tmp/run.jsonl") as fh:
    dracon.replay(dracon.read_jsonl(fh), tree_printer())
```

Useful for "where did the build spend its 12 minutes" post-mortems or for hooking a CI log into a viewer later.

## Wiring it into a `@dracon_program`

A common pattern: a `--progress` flag picks the subscriber, default off.

```python
from typing import Annotated, Literal
import sys
from pydantic import BaseModel
import dracon

@dracon.dracon_program(name="myprog")
class CLI(BaseModel):
    config: Annotated[str, dracon.Arg(is_file=True)]
    progress: Annotated[Literal["off", "tree", "jsonl"], dracon.Arg(help="progress display")] = "off"

    def run(self):
        sub = None
        if self.progress == "tree":
            sub = tree_printer()
        elif self.progress == "jsonl":
            sub = dracon.jsonl_writer(sys.stderr)
        with dracon.use_subscriber(sub):
            do_the_work(self.config)
```

`use_subscriber(None)` is a no-op, so the same code path covers "no progress" without a conditional.

## How it interacts with the rest of dracon

- **`trace=True` provenance** is unchanged. Trace records *what came from where*; progress records *what's happening now*. They emit to different sinks and can be enabled independently.
- **`!deferred`** — calling `subtree.construct(context=...)` emits a span scoped to that construction. Nested deferreds nest in the span tree naturally.
- **`!live`** — each `.resolve(component=c)` emits its own resolve span. Filter or drop sub-millisecond ones with `min_duration` if cheap live resolutions add noise.
- **Threads** — the active subscriber lives in a `ContextVar`, so it propagates cleanly into `asyncio.create_task` and `loop.run_in_executor`, but not into raw `threading.Thread` targets. If you need it there, capture the current context and run the target inside `ctx.run(target, ...)`.
