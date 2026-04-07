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
- YAML callables with `!fn`, `!fn:path`, and `!pipe`
- Runtime deferral with `!deferred` and `Resolvable[T]`
- `make_callable()` for turning YAML into reusable Python factories
- `dracon show` and provenance tracing for debugging composition

## Patterns Worth Knowing

### Dynamic Skeletons

One entry config can pick datasets and presets dynamically, instead of duplicating the same experiment config over and over:

```yaml
!set_default dataset_file: "datasets/genomics.yaml"
!set_default preset: "regression"

dataset: !include file:$DIR/${dataset_file}
<<{+>}: !include file:$DIR/presets/${preset}.yaml
```

That is the basic trick behind turning `M x N` near-duplicate configs into `1 + M + N`.

### Vocabulary Files

You can define reusable YAML tags in one file and import them into another:

```yaml
# mylib/vocabulary.yaml
!define Service: !fn
  !require name: "service name"
  !set_default port: 8080
  url: "https://${name}.internal:${port}"
```

```yaml
# config.yaml
<<(<): !include pkg:mylib:vocabulary.yaml

api: !Service { name: api, port: 443 }
worker: !Service { name: worker }
```

So you can build a shared config vocabulary without needing a bunch of Python-side glue.

### Late-Bound Runtime Pieces

Some parts of config only make sense once the program is already running. `!deferred` lets those parts wait:

```yaml
reporting: !deferred
  output_dir: "/runs/${run_id}"
  files:
    !each(name) ${logger_names}:
      - name: ${name}
        path: "/runs/${run_id}/${name}.json"
```

```python
reporting = config["reporting"].construct(
    context={"run_id": run_id, "logger_names": ["metrics", "artifacts"]},
)
```

So runtime-only values can still live in config instead of being reimplemented by hand in Python.

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
