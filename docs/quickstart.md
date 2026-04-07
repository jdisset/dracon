# Quickstart

## Install

```bash
pip install dracon
```

## Write some config

```yaml title="base.yaml"
environment: dev
log_level: ${getenv('LOG_LEVEL', 'INFO')}
workers: 1
database:
  host: localhost
  port: 5432
  <<: !include file:$DIR/db.yaml
```

```yaml title="db.yaml"
username: app_user
password: changeme
```

```yaml title="prod.yaml"
environment: prod
workers: 4
database:
  host: db.prod.internal
```

## Inspect it (no Python needed)

```bash
dracon show base.yaml prod.yaml
```

Output:

```yaml
environment: prod
log_level: INFO
workers: 4
database:
  host: db.prod.internal
  port: 5432
  username: app_user
  password: changeme
```

The two files are merged: `prod.yaml` overrides `base.yaml`, while unset fields (like `port`) carry through from the base.

## Add a Python model

```python title="app.py"
from pydantic import BaseModel
from typing import Annotated
from dracon import dracon_program, Arg

class Database(BaseModel):
    host: str = "localhost"
    port: int = 5432
    username: str = "app_user"
    password: str = "changeme"

@dracon_program(name="myapp")
class AppConfig(BaseModel):
    environment: Annotated[str, Arg(short='e', help="Target environment.")]
    log_level: str = "INFO"
    workers: Annotated[int, Arg(help="Worker process count.")] = 1
    database: Database = Database()

    def run(self):
        print(f"{self.environment}: {self.workers} workers, db={self.database.host}")

AppConfig.cli()
```

## Run it

```bash
python app.py +base.yaml +prod.yaml --workers 8
```

```
prod: 8 workers, db=db.prod.internal
```

Config files are prefixed with `+`. CLI flags override everything.

## What just happened

- `+base.yaml` and `+prod.yaml` were composed (includes resolved, values merged)
- `--workers 8` overrode the composed value
- The result was validated against `AppConfig` via Pydantic
- `AppConfig.run()` was called with the final, typed config object

## Next steps

- [Tutorial 1: Your First Config](tutorials/01-first-config.md) -- understand what just happened, step by step
