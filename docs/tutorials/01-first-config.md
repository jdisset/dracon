# Tutorial 1: Your First Config

You have a website monitoring tool called `webmon`. It checks a list of URLs on a timer and stores results in a database. You want to configure it from a YAML file, get a typed Python object back, and not think too hard about it.

This tutorial gets you from YAML to a validated Pydantic object in about 5 minutes.

## The model

Start with a Pydantic model that describes what your config looks like:

```python
# models.py
from pydantic import BaseModel

class DatabaseConfig(BaseModel):
    host: str = "localhost"
    port: int = 5432
    name: str = "webmon"
    password: str = ""

class WebmonConfig(BaseModel):
    sites: list[str] = []
    check_interval: int = 60
    database: DatabaseConfig = DatabaseConfig()
```

Nothing Dracon-specific here. Just normal Pydantic.

## The config files

Split the database config into its own file so it can be reused:

```yaml
# db.yaml
host: localhost
port: 5432
name: webmon
password: ${getenv('WEBMON_DB_PASSWORD', 'dev-pass')}
```

The `${getenv(...)}` part is a Dracon interpolation. It calls Python's `os.getenv` at load time. If the env var isn't set, it falls back to `"dev-pass"`.

Now the main config:

```yaml
# config.yaml
sites:
  - https://example.com
  - https://status.example.com

check_interval: 30

database: !include file:$DIR/db.yaml
```

Two things to note:

- `!include file:$DIR/db.yaml` pulls in the database config from a file relative to this one. `$DIR` always points to the directory of the current YAML file.
- The database password in `db.yaml` will be resolved when the config is loaded.

## Loading it

```python
# main.py
import dracon
from models import WebmonConfig

config = dracon.load("config.yaml")
wm = WebmonConfig.model_validate(config)

print(wm.sites)            # ['https://example.com', 'https://status.example.com']
print(wm.check_interval)   # 30
print(wm.database.host)    # 'localhost'
print(wm.database.password)  # whatever WEBMON_DB_PASSWORD is, or 'dev-pass'
```

`dracon.load()` returns a dict-like object with all includes resolved and interpolations evaluated. `model_validate` does the Pydantic validation on top.

## Cross-references with @

Say you want the database name to match the first site's domain. You can reference other parts of the config using `@/`:

```yaml
# config.yaml
sites:
  - https://example.com
  - https://status.example.com

check_interval: 30

database: !include file:$DIR/db.yaml
```

And in `db.yaml`:

```yaml
# db.yaml
host: localhost
port: 5432
name: "webmon_${@/sites[0].split('//')[1].replace('.', '_')}"
password: ${getenv('WEBMON_DB_PASSWORD', 'dev-pass')}
```

`@/sites[0]` refers to the first entry in `sites` at the root of the config. The rest is just Python string manipulation inside `${...}`. The result: `name` becomes `"webmon_example_com"`.

References starting with `@/` are absolute (from the config root). They are evaluated lazily, so it doesn't matter what order things appear in the file.

## Inspecting with `dracon show`

Before wiring up your app, you can check what the composed config looks like:

```bash
dracon show config.yaml
```

This loads the file, resolves includes, and prints the result as YAML. Add `-r` to also resolve interpolations:

```bash
dracon show config.yaml -r
```

Output (roughly):

```yaml
sites:
  - https://example.com
  - https://status.example.com
check_interval: 30
database:
  host: localhost
  port: 5432
  name: webmon_example_com
  password: dev-pass
```

Useful for debugging before your code ever touches the config.

## What you've learned

- Write a YAML config and load it into a Pydantic model with `dracon.load()`
- Use `!include file:$DIR/...` to split configs across files
- Use `${getenv(...)}` to pull in environment variables
- Use `@/path` to cross-reference other config values
- Use `dracon show` to inspect composed configs from the command line

Next up: [Tutorial 2: Build a CLI](02-build-a-cli.md), where you turn this config into a command-line program.
