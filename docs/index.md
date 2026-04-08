# Dracon

Dracon turns YAML configs into composable, type-safe Python objects. Define your schema as a Pydantic model, write your config in YAML with expressions and includes, and get a validated CLI for free.

## What it looks like

```yaml title="config.yaml"
log_level: ${getenv('LOG_LEVEL', 'INFO')}
workers: 2
database:
  host: db.${@/environment}.local
  port: 5432
  password: !include env:DB_PASS
```

```python title="app.py"
from pydantic import BaseModel
from dracon import dracon_program, Arg
from typing import Annotated

@dracon_program()
class App(BaseModel):
    environment: Annotated[str, Arg(short='e')]
    log_level: str = "INFO"
    workers: int = 1
    database: DatabaseConfig

App.cli()
```

```bash
python app.py +config.yaml -e prod --workers 8
```

## How it works

Dracon processes configuration in three phases:

- **Compose** -- YAML files are parsed, includes resolved, merges applied, and instructions (`!if`, `!define`, `!each`) executed. The result is a single YAML node graph. No Python objects exist yet.
- **Construct** -- The node graph is walked and turned into Python objects (Pydantic models, dicts, lists, primitives). Type validation happens here.
- **Resolve** -- Interpolations like `${@/environment}` are wrapped as lazy values and evaluated only when accessed. This lets expressions reference the final, fully-merged config.

## Start here

- [Quickstart](quickstart.md) -- zero to working in 90 seconds
- [Tutorial 1: Your First Config](tutorials/01-first-config.md) -- load YAML, get typed Python objects

## Features

- [Composable configs](guides/config-layering.md) -- includes, merges, layered overrides
- [Auto-generated CLIs](guides/cli-patterns.md) -- turn any Pydantic model into a CLI with `Arg` annotations
- [YAML functions (`!fn`, `!pipe`)](guides/yaml-functions.md) -- reusable templates and pipelines inside YAML
- [Type-safe with Pydantic](concepts/lifecycle.md) -- Pydantic validation, nested models, discriminated unions
- [The open vocabulary](concepts/open-vocabulary.md) -- values, constructors, and callables all become composable named building blocks
- [Deferred execution](guides/deferred-execution.md) -- values that depend on runtime context
- [Interpolation engine](reference/interpolation.md) -- embed Python expressions with `${...}`, reference other keys with `@/path`
- [Config introspection](guides/debugging.md) -- `dracon show` to inspect composition before writing Python
- [Real-world patterns](patterns/index.md) -- runtime contracts, layered vocabularies, hybrid pipelines, dynamic skeletons
