# CLI API

Python API for building CLI programs from Pydantic models.

```python
from dracon import Arg, Subcommand, subcommand, dracon_program, ConfigFile, HelpSection, make_program, make_callable
```

---

## Arg

Dataclass that maps a Pydantic field to CLI arguments. Applied via `Annotated`:

```python
class Config(BaseModel):
    name: Annotated[str, Arg(short="n", help="Your name")]
    output: Annotated[str, Arg(positional=True, is_file=True)]
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `help` | `str` | `None` | Help text. Falls back to field's `description`. |
| `short` | `str` | `None` | Short flag (e.g. `"n"` for `-n`). |
| `long` | `str` | `None` | Long flag (e.g. `"name"` for `--name`). Auto-generated from field name if not set. |
| `positional` | `bool` | `False` | Treat as a positional argument instead of `--flag`. |
| `is_file` | `bool` | `False` | Treat the value as a config file path: the file is loaded and composed as YAML, then merged into the field. Supports selectors (`model.yaml@encoder`). |
| `is_flag` | `bool` | `None` | Force flag behavior (no value). `None` = auto-detect from `bool` type. |
| `action` | `Callable` | `None` | Callback `(program, value) -> Any` triggered when the flag is parsed. |
| `default_str` | `str` | `None` | Override the default value display in help text. |
| `auto_dash_alias` | `bool` | `None` | Replace `_` with `-` in the long flag. `None` inherits from the program default (`True`). |
| `raw` | `bool` | `False` | Skip YAML composition; pass the CLI string value as-is. |
| `subcommand` | `bool` | `False` | Mark this field as a subcommand discriminator (usually set via `Subcommand()` instead). |

---

## Subcommand

Type factory for discriminated union subcommands.

```python
class CLI(BaseModel):
    command: Subcommand(TrainCmd, EvalCmd, discriminator='action')
```

### Signature

```python
Subcommand(*cmd_types, discriminator='action', **arg_kwargs)
```

Returns `Annotated[Union[cmd_types...], Field(discriminator=...), Arg(subcommand=True, positional=True)]`.

The `**arg_kwargs` are forwarded to the inner `Arg`.

---

## @subcommand

Decorator that injects a `Literal` discriminator field into a `BaseModel`.

```python
@subcommand("train")
class TrainCmd(BaseModel):
    epochs: int = 10
    # 'action' field is auto-injected: action: Literal["train"] = "train"
```

### Signature

```python
@subcommand(name: str, discriminator: str = 'action')
```

---

## @dracon_program

Decorator that turns a Pydantic `BaseModel` into a full CLI program.

```python
@dracon_program(name="mytool", version="1.0")
class Config(BaseModel):
    input: Annotated[str, Arg(positional=True)]
    verbose: bool = False

Config.cli()  # parse sys.argv
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | Class name | Program name in help output. |
| `version` | `str` | `None` | Version string (shown with `--version`). |
| `description` | `str` | Class docstring | Help description text. |
| `context_types` | `list[type]` | `None` | Types added to interpolation context as `{TypeName: type}`. |
| `context` | `dict` | `None` | Additional interpolation context. |
| `deferred_paths` | `list[str]` | `[]` | Paths forced to `DeferredNode`. |
| `auto_context` | `bool` | `False` | Capture types from the decorator's call site namespace. |
| `sections` | `list[HelpSection]` | `None` | Extra sections appended to help output. |
| `epilog` | `str` | `None` | Text at the bottom of help output. |
| `config_files` | `list[ConfigFile]` | `[]` | Auto-discovered config files, loaded as the base layer (below CLI args). |

### Generated Methods

All methods are classmethods on the decorated class:

#### `.cli(argv=None)`

Parse CLI args (defaults to `sys.argv[1:]`), construct the model, and call `.run()` if defined. Config files from `config_files` are auto-discovered and loaded as the base layer.

#### `.invoke(*configs, **context_kwargs)`

Load from config file paths and context, construct, then call `.run()`.

```python
Config.invoke("train.yaml", lr=0.001)
```

#### `.from_config(*configs, **context_kwargs)`

Like `.invoke()` but returns the model instance without calling `.run()`.

#### `.load(path, context=None)`

Low-level: load a single config file and validate as the model type.

### Built-in Flags

Every `@dracon_program` includes:

| Flag | Description |
|------|-------------|
| `-h`, `--help` | Print help panel and exit. |
| `--trace PATH` | Show composition provenance for a dotted keypath. |
| `--trace-all` | Show provenance for all values. |

### CLI Argument Parsing

- `+file.yaml` -- load as an additional config layer (merged left to right)
- `++var=value` or `++var value` -- set context variable for `${...}` expressions
- `--define.var=value` or `--define.var value` -- long form of `++`
- `--flag value` or `--flag=value` -- set a named option
- Short flags cannot be combined: use `-c -r -j`, not `-crj`

---

## CLI flags from config layers

Top-level `!require` and `!set_default` directives in any `+`-layered config
become real argparse flags at runtime. Adding a new flag for an experiment
becomes a config edit, not a code edit.

```yaml
# plugins/analytics.yaml
!require api_key:
  help: "API key for the analytics service"

!set_default:int batch_size:
  default: 32
  help: "batch size"
  short: -b
```

```bash
mycli +plugins/analytics.yaml --api-key $SECRET -b 64
mycli +plugins/analytics.yaml --help    # shows --api-key and --batch-size
```

### What makes a directive CLI-visible

- It is at the **top level** of a layered config (a `+file.yaml` argument).
- It is `!require` or `!set_default` (typed variants like
  `!set_default:int` count too, with `int` becoming the argparse `type=`).
- It is **not** nested inside `!fn`, `!deferred`, or `!if` branches —
  those are inner scopes by construction.

### Precedence

When the same name is declared in multiple places, the resolution order is:

```
model field (Pydantic)  >  YAML directive  >  context seed  >  default
```

Specifically:

- A model field shadows a YAML directive of the same name. `--port`
  routes to the model field; the YAML variable is still reachable via
  `++port=...` or `--define.port=...`.
- Multiple layers declaring the same name: last layer wins for the
  argparse metadata (help/short/default).
- A short alias that collides with an existing model-side `Arg` is
  dropped with one warning; the long flag still works.

### Why `++` still exists

`++name=value` (and its long form `--define.name=value`) bypass all flag
discovery. Reach for them when:

- A model field shadows a YAML variable of the same name and you need
  to write the YAML variable explicitly.
- A name has no declaration anywhere — `++` is the generic, ad-hoc
  context injection rail.
- A discovered flag's argparse coercion gets in the way and you want
  to feed a raw YAML literal instead (e.g. `++weights="[0.1, 0.2]"`).

### Inspecting at runtime

Set `DRACON_SHOW_VARS=1` to print a table of every defined variable at the
end of a CLI run. The `Source` column distinguishes `CLI (++/--define)`
from `CLI (--flag)` (a discovered flag) and `config (!define)` (a value
that came from the composed YAML itself).

The unused-variable warning fires when a variable was set on the CLI
(via any of the above) but no `${...}` interpolation, no `!set_default`,
and no `!require` ever read it.

---

## ConfigFile

Declares a config file for auto-discovery.

```python
@dracon_program(config_files=[
    ConfigFile("~/.mytool/config.yaml"),
    ConfigFile(".mytool.yaml", search_parents=True),
])
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str` | required | File path. Supports `~` expansion. |
| `search_parents` | `bool` | `False` | Walk up the directory tree looking for the file. Uses `cascade:` loader internally. Must be a relative path. |
| `required` | `bool` | `False` | Raise `FileNotFoundError` if not found. |
| `selector` | `str` | `None` | Keypath selector appended as `@selector` to the include string. |

---

## HelpSection

Extra section in CLI help output.

```python
HelpSection(title="Examples", body="  mytool train config.yaml\n  mytool eval --checkpoint best.pt")
```

---

## make_program

Low-level factory. Creates a `Program` object without decorating a class.

```python
prog = make_program(Config, name="mytool", version="1.0")
instance, raw_args = prog.parse_args(["--input", "data.csv"])
```

---

## make_callable

Turn a YAML config file or `DeferredNode` into a reusable callable.

```python
from dracon import make_callable

fn = make_callable("file:template.yaml", context_types=[MyModel])
result = fn(param1="value", param2=42)
```

### Signature

```python
make_callable(
    path_or_node: str | Path | DeferredNode,
    context: dict = None,
    context_types: list[type] = None,
    auto_context: bool = False,
    **loader_kwargs,
)
```

When given a file path, the entire file is loaded with `deferred_paths=['/']` to produce a `DeferredNode`. The returned callable accepts `**kwargs` that are injected as context, then constructs the result.

| Parameter | Description |
|-----------|-------------|
| `path_or_node` | File path string or existing `DeferredNode`. |
| `context` | Base context dict (types, functions, values). |
| `context_types` | List of types added as `{TypeName: type}`. |
| `auto_context` | Capture types from the caller's namespace. |
| `**loader_kwargs` | Forwarded to `DraconLoader` (e.g. `deferred_paths`, `interpolation_engine`). |
