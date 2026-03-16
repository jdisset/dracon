# How-To: Customize CLI Arguments

Dracon automatically generates CLI arguments from your Pydantic model, but you can customize them using `typing.Annotated` and `dracon.Arg`.

## Basic Customization (`Arg`)

Import `Arg` and use it within `Annotated` on your model fields.

```python
from pydantic import BaseModel
from typing import Annotated
from dracon import Arg

class CliConfig(BaseModel):
    input_file: Annotated[str, Arg(
        positional=True, # Make it a positional arg (order matters)
        help="Path to the input data file." # Custom help text
    )]
    output_dir: Annotated[str, Arg(
        short='o', # Add a short flag -o
        long='output-directory', # Custom long flag --output-directory
        help="Directory to save results."
    )]
    threshold: Annotated[float, Arg(help="Processing threshold.")] = 0.5
    verbose: Annotated[bool, Arg(
        short='v',
        help="Enable verbose output."
        # is_flag=True is automatic for bool
        )] = False
    force_update: Annotated[bool, Arg(
         long='force', # only long flag --force
         short=None   # explicitly disable short flag
         )] = False
```

**Common `Arg` Parameters:**

- `short`: A single character for the short flag (e.g., `'o'` for `-o`). Default derived if possible, otherwise none.
- `long`: String for the long flag (e.g., `'output-directory'` for `--output-directory`). Default is derived from field name (e.g., `output_dir` -> `output-dir`).
- `help`: Description shown in the `--help` message.
- `positional`: `True` to make the argument positional instead of an option. Order defined by field order in the model.
- `is_flag`: `True` for boolean flags (no value needed, presence means `True`). `False` to require an explicit value (`--verbose true`). Default is `True` for `bool` types.
- `default_str`: Custom string representation of the default value for the help message (overrides automatic formatting).

## Marking Arguments for File Loading (`is_file`)

If an argument represents a path to _another_ configuration file that Dracon should load and merge, set `is_file=True`. This tells the CLI parser to treat the provided value like a `+filename` argument internally.

```python
from pydantic import BaseModel
from typing import Annotated
from dracon import Arg

class SecretsConfig(BaseModel):
    api_key: str
    secret_token: str

class MainConfig(BaseModel):
    base_url: str
    # This argument expects a path to a YAML file defining SecretsConfig
    secrets: Annotated[SecretsConfig, Arg(
        is_file=True, # Treat the value as a file path to load
        help="Path to secrets YAML file."
    )]
```

**Usage:**

```bash
# Pass the path to the secrets file directly
$ python your_app.py --base-url http://example.com --secrets path/to/my_secrets.yaml
```

Dracon's CLI parser will see `--secrets path/to/my_secrets.yaml`, recognize `is_file=True`, and internally treat it as if `+path/to/my_secrets.yaml` was given, loading and merging its contents into the `secrets` field of the `MainConfig` object (expecting `!SecretsConfig` tag or structure match).

## Delaying Value Processing (`resolvable=True`)

Sometimes, you need to process an argument's value _after_ the initial CLI parsing, perhaps based on other arguments or loaded config. Use `resolvable=True` combined with `dracon.Resolvable` type hint.

```python
from pydantic import BaseModel
from typing import Annotated
from dracon import Arg, Resolvable, construct

class PostProcessingConfig(BaseModel):
    input_path: Annotated[str, Arg(positional=True)]
    # We want to finalize the output path later
    output_path: Annotated[Resolvable[str], Arg(
        resolvable=True, # Mark for deferred resolution
        help="Output path pattern (e.g., '{input}_out.txt')."
    )]

# --- In your main script ---
# config, _ = program.parse_args(...) # Parse args as usual

# 'config.output_path' is a Resolvable object here

# Perform logic based on other args/config
final_output = construct(
    config.output_path,
    context={'input': config.input_path} # Provide context needed for resolution
)
# Now 'final_output' is the resolved string

print(f"Final output path: {final_output}")
```

See the [Deferred Execution Guide](use-deferred.md) for more on `Resolvable`.

## Post-Parse Actions (`action`)

Execute a function **after** the full config is generated. The action receives the `Program` instance and the validated config object. If it returns a non-`None` value, that value replaces the config.

```python
import json, sys

def export_json(program, config):
    """Export the final config as JSON and exit."""
    print(json.dumps(config.model_dump(), indent=2))
    sys.exit(0)

class AppConfig(BaseModel):
    export: Annotated[bool, Arg(
        short='x',
        action=export_json,
        help="Export final config as JSON and exit."
    )] = False
    log_level: str = "INFO"
    workers: int = 4
```

Actions are collected during parsing and executed after config generation, so they have access to the fully merged and validated config.

## Collection Arguments (Lists and Dictionaries)

Dracon supports user-friendly syntaxes for list and dictionary arguments, making it easy to pass complex data structures via the command line.

### List Arguments

For fields typed as `List[T]`, `Tuple[T, ...]`, `Set[T]`, or other list-like containers, Dracon accepts multiple input formats:

```python
from pydantic import BaseModel
from typing import Annotated, List, Tuple, Set
from dracon import Arg

class CollectionConfig(BaseModel):
    tags: Annotated[List[str], Arg(help="List of tags to apply.")] = ["default"]
    coordinates: Annotated[Tuple[int, ...], Arg(help="Coordinate values.")] = ()
    categories: Annotated[Set[str], Arg(help="Unique categories.")] = set()
```

**Usage options:**

```bash
# Space-separated values (intuitive)
$ python app.py --tags web api backend --coordinates 10 20 30

# Traditional YAML/JSON syntax (also supported)
$ python app.py --tags "['web', 'api', 'backend']" --coordinates "(10, 20, 30)"

# For positional list arguments
$ python app.py web api backend  # if tags is marked positional=True
```

### Dictionary Arguments

For fields typed as `Dict[K, V]` or other dict-like containers, Dracon provides multiple convenient syntaxes:

```python
from pydantic import BaseModel
from typing import Annotated, Dict, Any
from dracon import Arg

class ConfigWithDict(BaseModel):
    settings: Annotated[Dict[str, Any], Arg(help="Configuration settings.")] = {}
    metadata: Annotated[Dict[str, str], Arg(help="Additional metadata.")] = {}
```

**Usage options:**

```bash
# Key=value pairs (shell-friendly)
$ python app.py --settings debug=true port=8080 host=localhost

# Nested keys with dot notation
$ python app.py --settings app.name=myapp app.version=1.0 cache.enabled=true

# Mixed approaches
$ python app.py --settings timeout=30 database.host=db.example.com

# Traditional JSON syntax (also supported)
$ python app.py --settings '{"debug": true, "port": 8080}'

# For positional dict arguments
$ python app.py debug=true port=8080  # if settings is marked positional=True
```

**Important Notes:**

- When using positional arguments, only **one** collection argument (list or dict) is allowed per command
- Values are automatically quote-stripped if wrapped in single or double quotes
- Nested dictionary keys use dot notation: `parent.child.key=value`
- Both syntaxes can be mixed with file loading: `--settings +config.yaml debug=true`

## Subcommands

Use subcommands to split your CLI into distinct actions, each with their own arguments — like `git commit`, `git push`, etc.

### Define Subcommand Models

Each subcommand is a `BaseModel` with an `action` discriminator field and (optionally) a `.run(ctx)` method:

```python
from dracon import Arg, Subcommand, dracon_program
from pydantic import BaseModel
from typing import Annotated, Literal

class TrainCmd(BaseModel):
    """Train a model on the dataset."""
    action: Literal['train'] = 'train'
    epochs: Annotated[int, Arg(help="Number of training epochs")] = 10
    lr: float = 0.001

    def run(self, ctx):
        # ctx is the root CLI instance — access shared options here
        print(f"Training (verbose={ctx.verbose}) for {self.epochs} epochs")

class EvalCmd(BaseModel):
    """Evaluate model performance."""
    action: Literal['eval'] = 'eval'
    dataset: Annotated[str, Arg(help="Path to test dataset")]

    def run(self, ctx):
        print(f"Evaluating on {self.dataset}")
```

### Wire Into Root Model

Use `Subcommand()` on the root model to declare the union:

```python
@dracon_program(name="ml-tool", version="1.0")
class CLI(BaseModel):
    verbose: Annotated[bool, Arg(short='v', help="Verbose output")] = False
    command: Subcommand(TrainCmd, EvalCmd)
```

That's it. Run with:

```bash
ml-tool train --epochs 50
ml-tool --verbose eval --dataset test.csv
ml-tool train --help
```

### Skip the Discriminator Boilerplate

The `@subcommand` decorator injects the `action: Literal[...] = ...` field for you:

```python
from dracon import subcommand

@subcommand('train')
class TrainCmd(BaseModel):
    """Train a model."""
    epochs: int = 10
    # action: Literal['train'] = 'train' is added automatically
```

### Subcommand-Scoped Config Files

Config files appearing **after** the subcommand name are scoped to it — the file only needs the subcommand's own fields, no wrapper:

```bash
ml-tool train +training.yaml --lr 0.0001
```

```yaml
# training.yaml
epochs: 99
lr: 0.01
```

Files **before** the subcommand merge at the root level:

```bash
ml-tool +base.yaml train
```

### Nested Subcommands

Subcommand models can contain their own `Subcommand` fields for multi-level CLIs:

```python
class AddCmd(BaseModel):
    action: Literal['add'] = 'add'
    name: Annotated[str, Arg(help="Remote name")]

class RemoveCmd(BaseModel):
    action: Literal['remove'] = 'remove'
    name: Annotated[str, Arg(help="Remote name")]

class RemoteCmd(BaseModel):
    """Manage remotes."""
    action: Literal['remote'] = 'remote'
    sub: Subcommand(AddCmd, RemoveCmd)
```

```bash
my-tool remote add --name origin
```

See the [Subcommand reference](../reference/cli_arg.md#subcommands) for full API details.

By combining these `Arg` parameters, you can create sophisticated and user-friendly command-line interfaces directly from your Pydantic configuration models.

## Auto-Discovered Config Files (`ConfigFile`)

Programs can declare config files that are automatically discovered and loaded as a base layer — like `.gitconfig`, `Cargo.toml`, or `.eslintrc`. Users get sensible defaults without passing `+file.yaml` on every invocation.

```python
from dracon import dracon_program, ConfigFile

@dracon_program(
    name='my-tool',
    config_files=[
        ConfigFile('~/.my-tool/config.yaml'),              # home-dir defaults
        ConfigFile('.my-tool.yaml', search_parents=True),   # project-local override
    ],
)
class Config(BaseModel):
    host: str = "localhost"
    port: int = 8080
```

### ConfigFile Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | `str` | _(required)_ | File path (`~` is expanded) |
| `search_parents` | `bool` | `False` | Walk up from CWD to find the file |
| `required` | `bool` | `False` | Error if not found |
| `selector` | `str \| None` | `None` | Extract a subtree via `@keypath` |

### How Layering Works

Auto-discovered configs are prepended as `+file` args before any user-provided args. Standard dracon merge rules apply.

**Precedence (lowest → highest):**

1. Model field defaults
2. Auto-discovered configs (in declaration order)
3. Explicit CLI `+file.yaml`
4. CLI `--flag` / `--nested.path` overrides

### Parent Directory Search

With `search_parents=True`, dracon walks up from the current working directory toward root, looking for the first match. This lets projects drop a config file at any level:

```
~/projects/myapp/.my-tool.yaml    ← picked up when CWD is anywhere under myapp/
~/.my-tool/config.yaml            ← always available (no search, just expanduser)
```

### Example: Multi-Layer Tool Config

```yaml
# ~/.my-tool/config.yaml — user defaults
host: my-server.local
port: 443

# ~/projects/dev-env/.my-tool.yaml — project override
host: localhost
port: 8080
```

```bash
my-tool status                           # uses both configs, project wins
my-tool --port 9999 status               # CLI flag wins over everything
my-tool +/tmp/special.yaml status        # explicit +file layers between auto and flags
```

!!! note
    `search_parents=True` requires a relative path. Absolute paths raise `ValueError` since parent-walking is meaningless for them.
