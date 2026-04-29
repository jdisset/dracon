# Tutorial 2: Build a CLI

In [Tutorial 1](01-first-config.md), you loaded a YAML config for `webmon` into a Pydantic model. That works fine for a library, but if you're building a CLI tool, you want users to be able to pass flags, override values, and point at config files from the command line.

Dracon generates a CLI directly from your Pydantic model. No argparse boilerplate, no click decorators. You annotate your fields, and it handles the rest.

## Adding the decorator

Start from the model in Tutorial 1 and add `@dracon_program`:

```python
# webmon.py
from pydantic import BaseModel, Field
from typing import Annotated
from dracon import dracon_program, Arg

class DatabaseConfig(BaseModel):
    host: str = "localhost"
    port: int = 5432
    name: str = "webmon"
    password: str = ""

@dracon_program(name="webmon", description="Monitor websites and report downtime.")
class WebmonConfig(BaseModel):
    sites: Annotated[
        list[str],
        Arg(positional=True, help="URLs to monitor"),
    ]

    check_interval: Annotated[
        int,
        Arg(short="i", help="Seconds between checks"),
    ] = 60

    notify_email: Annotated[
        str,
        Arg(short="n", help="Email address for alerts"),
    ] = ""

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)

    def run(self):
        print(f"Monitoring {len(self.sites)} sites every {self.check_interval}s")
        print(f"Database: {self.database.host}:{self.database.port}/{self.database.name}")
        if self.notify_email:
            print(f"Alerts go to: {self.notify_email}")

if __name__ == "__main__":
    WebmonConfig.cli()
```

A few things happened:

- `@dracon_program` wires up the CLI. It reads your model's fields and builds argument parsing from them.
- `Arg(positional=True)` makes `sites` a positional argument, so users write URLs directly, not after a flag.
- `Arg(short="i")` gives `check_interval` a `-i` shorthand.
- The `run()` method is called automatically after parsing. If you define it, `.cli()` will parse args and then call it.

## Running it

```bash
python webmon.py https://example.com https://status.example.com
```

Output:

```
Monitoring 2 sites every 60s
Database: localhost:5432/webmon
Alerts go to:
```

## What --help looks like

```bash
python webmon.py --help
```

This prints a structured help page with:

- The program description ("Monitor websites and report downtime.")
- A list of positional arguments (`sites`)
- All flags with their types, defaults, and help text (`--check-interval`, `-i`, `--notify-email`, `-n`)
- Nested fields shown as dotted paths (`--database.host`, `--database.port`, etc.)

You didn't write any of that. It came from the model fields and `Arg()` annotations.

## Overriding values with flags

Flags use the field name. Underscores become dashes automatically:

```bash
python webmon.py https://example.com --check-interval 15 --notify-email ops@example.com
```

For nested models, use dot notation:

```bash
python webmon.py https://example.com --database.host db.prod.internal --database.port 5433
```

These overrides apply on top of whatever the defaults (or config files) provide.

## Loading config files with +file

Remember the YAML files from Tutorial 1? You can load them from the command line with the `+` prefix:

```bash
python webmon.py +config.yaml
```

This loads `config.yaml` as the base config, then applies any CLI flags on top. You can stack multiple files; they merge left to right:

```bash
python webmon.py +config.yaml +prod-overrides.yaml --check-interval 10
```

Order matters. Later sources override earlier ones. So this gives you:

1. `config.yaml` as the base
2. `prod-overrides.yaml` merged on top
3. `--check-interval 10` as the final override

## Context variables with ++

Sometimes your config files use `${...}` interpolations that depend on context, like an environment name. You can inject those from the CLI with `++`:

```bash
python webmon.py +config.yaml ++env=prod
```

If your `config.yaml` has something like:

```yaml
database:
  host: "db.${env}.internal"
```

Then `++env=prod` sets the `env` variable, and the host resolves to `"db.prod.internal"`.

You can also write it with a space instead of `=`:

```bash
python webmon.py +config.yaml ++env prod
```

## Putting it together

A realistic invocation might look like:

```bash
python webmon.py \
  +config.yaml \
  ++env=prod \
  --database.password s3cret \
  --check-interval 30 \
  https://example.com https://status.example.com
```

This loads the config file, sets the `env` context variable, overrides the database password and check interval, and passes two sites as positional args. The model is validated by Pydantic, `run()` is called, and you're off.

## Beyond .cli()

The decorator also adds a few other class methods:

- `WebmonConfig.from_config("config.yaml", env="prod")` loads a config file with context variables and returns the validated model, without calling `run()`. Good for tests or embedding in a larger app.
- `WebmonConfig.invoke("config.yaml", env="prod")` does the same but also calls `run()`.

## What you've learned

- `@dracon_program` turns a Pydantic model into a CLI program
- `Arg()` controls how fields map to CLI arguments (positional, short flags, help text)
- `+file.yaml` loads config files from the command line
- `--flag value` sets any declared option — Pydantic field or top-level `!require` / `!set_default` in a layered config
- `--nested.path value` overrides nested model fields
- `++var=value` injects context variables for `${...}` interpolations (escape hatch when a name has no declaration or collides with a model field)
- `run()` is dispatched automatically after parsing

Next: subcommands, config file auto-discovery, and more advanced patterns.
