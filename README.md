# Dracon

<img src="https://raw.githubusercontent.com/jdisset/dracon/main/docs/dracon_logo.svg" alt="Dracon Logo" width="250"/>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Documentation](https://img.shields.io/badge/docs-available-brightgreen.svg)](https://jdisset.github.io/dracon/)

Dracon turns YAML configs into composable, type-safe Python objects. Define your schema as a Pydantic model, write config in YAML with includes and expressions, and get a validated CLI from the same model.

## Why Dracon?

Most config systems I've had the pleasure to deal with were either:

- **Too simple**: "just a dict, `argparse`, and pain"
- **Too magical**: opaque frameworks that make it weirdly hard to tell what config you are actually running
- **Too rigid**: powerful, but with a pretty strong idea of the Proper Way, and somehow you end up fighting the config system instead of getting work done

I built Dracon to hit the "powerful but transparent" middle ground. Especially in ML and research codebases, config tends to come from everywhere at once: package defaults, local files, environment variables, layered overrides, CLI flags, runtime values, and random YAML fragments living in places they probably shouldn't. Dracon gives you a small set of tools to catch all of that and turn it into something explicit, typed, declarative, highly composable and easy to work with.

## What It Looks Like

```yaml
# config.yaml
log_level: ${getenv('LOG_LEVEL', 'INFO')}
workers: 2
database:
  host: db.${@/environment}.local
  port: 5432
  password: !include env:DB_PASS
```

```python
from typing import Annotated

from pydantic import BaseModel

from dracon import Arg, dracon_program


class DatabaseConfig(BaseModel):
    host: str
    port: int
    password: str


@dracon_program(name="myapp")
class App(BaseModel):
    environment: Annotated[str, Arg(short="e")]
    log_level: str = "INFO"
    workers: int = 1
    database: DatabaseConfig


if __name__ == "__main__":
    App.cli()
```

```bash
python app.py +config.yaml -e prod --workers 8
```

## How It Works

Dracon processes configuration in three phases:

- **Compose**: parse YAML, resolve includes, apply merges, run instructions like `!define`, `!if`, and `!each`
- **Construct**: turn the resulting node tree into Python objects and validate typed models with Pydantic
- **Resolve**: evaluate lazy `${...}` expressions when needed, and construct deferred subtrees later if they depend on runtime context

That separation is a big part of the point. You can inspect the composed config before construction with `dracon show`, instead of treating config loading as one opaque step.

## Quick Start

Install:

```bash
pip install dracon
```

Write two config files:

```yaml
# base.yaml
environment: dev
workers: 1
database:
  host: localhost
  port: 5432
  <<: !include file:$DIR/db.yaml
```

```yaml
# prod.yaml
environment: prod
workers: 4
database:
  host: db.prod.internal
```

Inspect the merged result before writing any Python:

```bash
dracon show base.yaml prod.yaml
```

Then wire it to a Pydantic model with `@dracon_program` and run:

```bash
python app.py +base.yaml +prod.yaml --workers 8
```

## What You Get

- Layered configs with `!include`, merge keys, selectors, and optional overlays
- Standard CLIs generated from Pydantic models, with nested overrides and config-file layering
- `!require` / `!set_default` directives that double as CLI flags: layered configs grow the flag set and `--help` text without touching the model
- YAML callables with `!fn`, `!fn:path`, and `!pipe`
- Runtime deferral with `!deferred` and `Resolvable[T]`
- `make_callable()` for turning YAML into reusable Python factories
- `dracon show` and provenance tracing for debugging composition
- Bidirectional vocabulary: `dump`/`dump_to_node` round-trip Pydantic models and dracon-native wrappers through the same `SymbolTable` that drives the load path
- `dump_line`/`loads_line`/`document_stream` for line-framed wire protocols and log-replay streams

## Patterns Worth Knowing

### Layered Vocabularies

Vocabulary files can build on other vocabulary files, so users only see the higher-level tags:

```yaml
# infra.yaml
!define Service: !fn
  !require name: "service name"
  !set_default port: 8080
  !fn :
    url: "https://${name}.internal:${port}"

# ml.yaml
<<(<): !include pkg:mylib:infra.yaml

!define Experiment: !fn
  !require name: "experiment"
  !fn :
    api: !Service { name: "${name}-api", port: 443 }

# config.yaml
<<(<): !include pkg:mylib:ml.yaml
run: !Experiment { name: genomics-v2 }
```

So a config vocabulary can layer cleanly instead of flattening back into Python every time it grows.

### Hybrid Pipelines

Pipelines can stay in YAML even when the stages are ordinary Python functions:

```yaml
!define vit_pipeline: !pipe
  - load_data
  - validate: { minimum: 2 }
  - train_vit

report: ${vit_pipeline(source='s3://raw')}
```

That gives you config-defined workflow shape without needing to move the actual stage logic out of Python.

### Runtime Contracts

Runtime-only config does not need to turn into hand-written glue:

```yaml
reporting: !deferred
  !require run_id: "runtime run identifier"
  !assert ${len(run_id) > 0}: "run_id must not be empty"

  output_dir: "/runs/${run_id}"
  summary:
    path: "/runs/${run_id}/summary.json"
```

```python
reporting = config["reporting"].construct(
    context={"run_id": run_id},
)
```

So the config itself declares what it needs at runtime and what should happen once those values exist.

The docs go deeper on these in the [Patterns](https://jdisset.github.io/dracon/patterns/) section.

## Documentation

- [Quickstart](https://jdisset.github.io/dracon/quickstart/)
- [Tutorials](https://jdisset.github.io/dracon/tutorials/01-first-config/)
- [Guides](https://jdisset.github.io/dracon/guides/)
- [Patterns](https://jdisset.github.io/dracon/patterns/)
- [Reference](https://jdisset.github.io/dracon/reference/)

## Acknowledgements

- [Pydantic](https://docs.pydantic.dev/)
- [ruamel.yaml](https://yaml.dev/doc/ruamel.yaml/)
- [asteval](https://lmfit.github.io/asteval/)
- [Diataxis Framework](https://diataxis.fr/)
