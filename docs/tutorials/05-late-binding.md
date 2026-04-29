# Tutorial 5: Late Binding

Some values don't exist when the config loads.

The webmon app needs a unique run ID at startup, and output paths depend on it. A database connection pool shouldn't be created until the program is actually running. An API key might come from a vault that requires authentication first.

This tutorial covers three mechanisms for deferring work, from simplest to most explicit.

## Lazy `!define`: construction on first access

The simplest case. You `!define` a variable with a type tag, and Dracon builds the object the first time something references it.

```yaml
# config.yaml
!set_default db_host: "localhost"
!set_default db_port: 5432

!define db: !DatabaseConfig
  host: ${db_host}
  port: ${db_port}

connection_string: "postgresql://${db.host}:${db.port}/webmon"
```

```python
# models.py
from pydantic import BaseModel

class DatabaseConfig(BaseModel):
    host: str
    port: int
```

```python
# main.py
import dracon
from models import DatabaseConfig

config = dracon.load("config.yaml", context={"DatabaseConfig": DatabaseConfig})
print(config["connection_string"])
# postgresql://localhost:5432/webmon
```

A few things to notice:

- `db_host` and `db_port` can be defined anywhere, even after the `!define db` block. Forward references work.
- `DatabaseConfig` is constructed only when `${db.host}` is first evaluated, not at parse time.
- If nothing ever references `${db}`, it is never constructed at all.

This is enough when all the information exists at composition time, just in scattered places. The order things appear in the file doesn't matter.

### Lazy defines are cached

A `!define` with a type tag is constructed once, then reused:

```yaml
!define db: !DatabaseConfig
  host: ${db_host}
  port: ${db_port}

host_check: ${db.host}
port_check: ${db.port}
```

Both `host_check` and `port_check` resolve against the same `DatabaseConfig` instance. One construction, no duplicates.

## When lazy `!define` isn't enough

Lazy defines resolve all their expressions at composition time. They can see `!define`d variables, `!set_default` values, environment variables, anything available during the load. But they cannot see values that only exist at runtime.

Some examples of runtime-only values:

- A UUID generated at startup
- A secret fetched from a vault after authentication
- A GPU device ID chosen by a scheduler
- User input from an interactive prompt

For those, you need `!deferred`.

## `!deferred`: pausing an entire subtree

A `!deferred` tag tells Dracon: "don't compose or construct this subtree yet. Store it as-is, and I'll tell you when."

```yaml
# config.yaml
sites:
  - https://example.com

report_path: !deferred "/data/${run_id}/report.html"
```

When you load this, `report_path` is not a string. It's a `DeferredNode`, a frozen subtree waiting for context.

```python
import dracon
from dracon import DeferredNode

config = dracon.load("config.yaml")

# report_path is paused
assert isinstance(config["report_path"], DeferredNode)

# provide the missing context and construct
report = config["report_path"].construct(context={"run_id": "abc123"})
print(report)  # /data/abc123/report.html
```

The key difference from lazy `!define`: you explicitly call `.construct()` and pass in runtime values through the `context` argument.

### Deferred subtrees can be arbitrarily complex

`!deferred` doesn't just work on scalars. It freezes entire subtrees, including `!include`, `!each`, `!if`, merge operators, and interpolations:

```yaml
# config.yaml
!set_default check_interval: 30

monitoring: !deferred
  run_id: ${run_id}
  output_dir: "/data/${run_id}"
  sites:
    !each(site) ${site_list}:
      - url: ${site}
        report: "/data/${run_id}/${site.split('//')[1]}.html"
```

```python
config = dracon.load("config.yaml")

monitoring = config["monitoring"].construct(context={
    "run_id": "run-2024-001",
    "site_list": ["https://example.com", "https://status.example.com"],
})

print(monitoring["output_dir"])
# /data/run-2024-001

print(monitoring["sites"][0]["report"])
# /data/run-2024-001/example.com.html
```

All the composition directives inside the `!deferred` block are evaluated during `.construct()`, not during the initial load. The `!each` loop, the interpolations, the string formatting: all of it waits.

If a deferred branch needs runtime logic to choose what to construct, give that choice a local name first:

```yaml
decision: !deferred
  !define Action: ${llm_decide(prompt='triage', metrics=jobs.meta(group='trials'))}
  !Action {}
```

That is usually nicer than trying to squeeze the whole selection directly into a dynamic tag.

### Copying before constructing

A `DeferredNode` can be constructed multiple times with different contexts. Use `.copy()` first to avoid mutating the original:

```python
node = config["monitoring"]

run_a = node.copy().construct(context={"run_id": "run-a", "site_list": sites})
run_b = node.copy().construct(context={"run_id": "run-b", "site_list": sites})
```

Each call gets its own independent construction.

## `Resolvable[T]`: deferred fields in Pydantic models

When you're working with typed Pydantic models, you sometimes want a specific field to stay unresolved until you provide context. `Resolvable[T]` does this, but it works through the **YAML tag**, not the type annotation alone. The YAML value must be tagged with `!Resolvable[str]` to tell dracon to pause construction on that field:

```python
# models.py
from pydantic import BaseModel
from dracon import Resolvable

class WebmonConfig(BaseModel):
    sites: list[str] = []
    check_interval: int = 60
    report_path: Resolvable[str]   # Pydantic accepts Resolvable instances here
```

```yaml
# config.yaml
!WebmonConfig
sites:
  - https://example.com
check_interval: 30
report_path: !Resolvable[str] "/data/${run_id}/report.html"
```

```python
import dracon
from models import WebmonConfig

config = dracon.load("config.yaml", context={"WebmonConfig": WebmonConfig})
assert isinstance(config, WebmonConfig)

# report_path is a Resolvable, not a string yet
lazy = config.report_path.resolve(context={"run_id": "abc123"})
path = lazy.resolve()       # force the lazy interpolation
print(path)                 # /data/abc123/report.html
```

The Pydantic type `Resolvable[str]` tells Pydantic to accept `Resolvable` instances. The `!Resolvable[str]` YAML tag tells dracon's constructor to wrap the value instead of resolving it.

For most cases, `!deferred` is simpler. Use `Resolvable` when you want the parent model fully constructed and validated, with only one field deferred.

## `Lazy[T]`: typed lazy interpolation

When the deferred bit is just a single `${...}` value (not a whole subtree), `Lazy[T]` is lighter than `Resolvable[T]`. It mirrors `Resolvable[T]`'s shape but resolves *automatically on attribute access* from a `LazyDraconModel`:

```python
from dracon import Lazy, LazyDraconModel, DraconLoader

class Server(LazyDraconModel):
    port: Lazy[int]
    host: Lazy[str] = "localhost"

cfg = DraconLoader().loads(
    "port: ${env_port}\nhost: ${env_host}",
    context={"env_port": 9000, "env_host": "api.local"},
)
cfg.port  # -> 9000   (typed as int, resolved on access)
cfg.host  # -> "api.local"
```

Use `Lazy[T]` when "the value will be available by the time something reads this field" is acceptable. Use `Resolvable[T]` when you need to control *when* a field resolves (e.g. for audit, runtime mutation, or pausing until a transaction begins).

## Worked example: webmon with deferred report paths

Putting it together. The webmon app generates a run ID at startup and uses it in output paths:

```yaml
# config.yaml
!set_default check_interval: 30

sites:
  - https://example.com
  - https://status.example.com

database:
  host: ${getenv('WEBMON_DB_HOST', 'localhost')}
  port: 5432

reporting: !deferred
  run_id: ${run_id}
  output_dir: "/var/webmon/${run_id}"
  site_reports:
    !each(site) ${site_list}:
      - url: ${site}
        path: "/var/webmon/${run_id}/${site.split('//')[1].replace('.', '_')}.html"
```

```python
# main.py
import uuid
import dracon

config = dracon.load("config.yaml")

# generate run ID at startup
run_id = str(uuid.uuid4())[:8]

# construct the deferred reporting subtree with runtime context
reporting = config["reporting"].construct(context={
    "run_id": run_id,
    "site_list": config["sites"],
})

print(f"Run: {reporting['run_id']}")
print(f"Output: {reporting['output_dir']}")

for report in reporting["site_reports"]:
    print(f"  {report['url']} -> {report['path']}")
```

Output:

```
Run: a1b2c3d4
Output: /var/webmon/a1b2c3d4
  https://example.com -> /var/webmon/a1b2c3d4/example_com.html
  https://status.example.com -> /var/webmon/a1b2c3d4/status_example_com.html
```

The non-deferred parts of the config (sites, database, check_interval) load normally. Only the `reporting` subtree waits for the run ID.

## Choosing the right tool

| Situation | Use |
| :-- | :-- |
| Object depends on other `!define`d variables | Lazy `!define x: !Type { ... }` |
| Value depends on runtime context | `!deferred` + `.construct(context=...)` |
| Single field in a Pydantic model needs user-driven late binding | `Resolvable[T]` + `.resolve(context=...)` |
| Single typed `${...}` value should resolve on attribute access | `Lazy[T]` on a `LazyDraconModel` field |

Start with lazy `!define`. If you find yourself needing to pass in values that don't exist at load time, switch to `!deferred`. If it's just one field in a model, choose between `Resolvable[T]` (explicit user-driven) and `Lazy[T]` (auto-on-access).

## What you've learned

- Lazy `!define` defers object construction until first access, handling forward references automatically
- `!deferred` freezes an entire subtree for later `.construct(context=...)` with runtime values
- `Resolvable[T]` defers a single Pydantic field, resolved with `.resolve(context=...)`
- Use `.copy()` before `.construct()` when you need to construct the same deferred node multiple times

Next up: this tutorial used simple `!deferred` syntax. Dracon also supports `clear_ctx`, typed deferred nodes (`!deferred:MyType`), rerooting, and more. Those are covered in the reference.
