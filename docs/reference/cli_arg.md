# CLI (`Arg`) Parameters

The `Arg` dataclass configures how Pydantic model fields are exposed as CLI arguments.

## Basic Usage

```python
from typing import Annotated, Literal
from pydantic import BaseModel
from dracon import Arg

class Config(BaseModel):
    port: Annotated[int, Arg(help="Server port")] = 8080
    debug: Annotated[bool, Arg(help="Enable debug mode")] = False
```

## `Arg` Parameters

### `help: str`
Help text displayed in CLI usage.

```python
port: Annotated[int, Arg(help="Port for the web server")] = 8080
```

### `short: str`
Single-character short flag.

```python
environment: Annotated[str, Arg(short='e', help="Deployment environment")]
# Creates: -e, --environment
```

### `positional: bool = False`
Make argument positional instead of optional.

```python
input_file: Annotated[str, Arg(positional=True, help="Input file path")]
# Usage: myapp input.txt (instead of --input-file input.txt)
```

### `resolvable: bool = False`
Mark argument for lazy evaluation/resolution.

```python
output_path: Annotated[str, Arg(resolvable=True, help="Output directory")]
# Allows deferred construction with runtime context
```

### `is_file: bool = False`
Treat argument value as a file path and load its contents.

```python
config: Annotated[dict, Arg(is_file=True, help="Configuration file")]
# Automatically prefixes argument with '+' for file loading
# --config myfile.yaml becomes +myfile.yaml internally
```

### `long: str`
Explicit long flag name (overrides auto-derived name).

```python
output_dir: Annotated[str, Arg(long='output-directory', help="Output directory")]
# Creates: --output-directory (instead of auto-derived --output-dir)
```

### `is_flag: bool = None`
Whether the argument is a boolean flag (no value required). `None` means auto-detect (`True` for `bool` fields).

```python
verbose: Annotated[bool, Arg(is_flag=True, help="Verbose output")]
# Usage: --verbose (no value needed, presence sets True)
```

### `action: Callable`
Callback executed **after** config generation: `(program, config) -> Any`. If the return value is not `None`, it replaces the config.

```python
def export_config(program, config):
    """Export the final config as JSON and exit."""
    import json, sys
    print(json.dumps(config.model_dump(), indent=2))
    sys.exit(0)

class Config(BaseModel):
    export: Annotated[bool, Arg(action=export_config, help="Export config as JSON")] = False
```

### `default_str: str`
Custom default value representation in help.

```python
workers: Annotated[int, Arg(
    default_str="CPU count",
    help="Number of worker processes"
)] = None  # Actual default computed later
```

### `auto_dash_alias: bool = None`
Controls `_` to `-` conversion in the long flag name. `None` inherits from the program's `default_auto_dash_alias` setting (which defaults to `True`). When enabled, underscores in the field name are **replaced** with dashes to form the CLI flag.

```python
max_connections: Annotated[int, Arg(help="Maximum connections")]
# Creates --max-connections (underscores replaced with dashes)

raw_name: Annotated[str, Arg(auto_dash_alias=False, help="No dash alias")]
# Creates --raw_name (underscores kept as-is)
```

### `subcommand: bool = False`
Marks this field as a subcommand union. Automatically set by `Subcommand()` — you don't need to set this manually.

## Subcommands

### `Subcommand(*cmd_types, discriminator='action', **arg_kwargs)`

Type factory that creates the correct `Annotated[Union[...], Field(discriminator=...), Arg(subcommand=True)]` annotation for a subcommand field.

```python
from dracon import Subcommand

class CLI(BaseModel):
    command: Subcommand(TrainCmd, EvalCmd)
    # equivalent to:
    # command: Annotated[
    #     Union[TrainCmd, EvalCmd],
    #     Field(discriminator='action'),
    #     Arg(subcommand=True, positional=True),
    # ]
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `*cmd_types` | `type[BaseModel]` | (required) | Subcommand model classes |
| `discriminator` | `str` | `'action'` | Field name used to distinguish subcommands |
| `**arg_kwargs` | | | Additional kwargs passed to `Arg()` |

Each subcommand type must have a discriminator field with a `Literal` type:

```python
class TrainCmd(BaseModel):
    action: Literal['train'] = 'train'  # discriminator
    epochs: int = 10
```

### `@subcommand(name, discriminator='action')`

Decorator that injects the discriminator field automatically, removing the boilerplate:

```python
from dracon import subcommand

@subcommand('train')
class TrainCmd(BaseModel):
    epochs: int = 10
    # action: Literal['train'] = 'train' is injected automatically

@subcommand('eval')
class EvalCmd(BaseModel):
    dataset: str
```

Custom discriminator field name:

```python
@subcommand('deploy', discriminator='cmd')
class DeployCmd(BaseModel):
    target: str = "prod"
    # cmd: Literal['deploy'] = 'deploy' is injected
```

### Subcommand Help Output

**Top-level** (`ml-tool --help`):

```
ml-tool (v1.0)

  Usage: ml-tool [OPTIONS] COMMAND [COMMAND_OPTIONS]

  Commands:
    train    Train a model on the dataset.
    eval     Evaluate a model on test data.

  Options:
    -v, --verbose
      Verbose output
      [default: False]

  Use 'ml-tool COMMAND --help' for more info on a command.
```

**Per-subcommand** (`ml-tool train --help`):

```
ml-tool train

  Train a model on the dataset.

  Usage: ml-tool train [OPTIONS]

  Options:
    --epochs  int
      Number of epochs
      [default: 10]

    --lr  float
      [default: 0.001]

  Shared Options:
    -v, --verbose
      Verbose output
      [default: False]
```

### Subcommand Config Files

Config files placed **after** the subcommand name are scoped to that subcommand — their contents are merged under the subcommand field:

```bash
ml-tool train +training.yaml    # training.yaml is merged into command:
```

```yaml
# training.yaml — no wrapper needed, just the subcommand's fields:
epochs: 99
lr: 0.01
```

Config files **before** the subcommand merge at root level:

```bash
ml-tool +base.yaml train        # base.yaml merges at root
```

A full config can also specify the subcommand inline:

```yaml
# full_config.yaml
verbose: true
command:
  action: train
  epochs: 50
```

### Nested Subcommands

Subcommand models can themselves contain `Subcommand` fields:

```python
class AddCmd(BaseModel):
    action: Literal['add'] = 'add'
    name: Annotated[str, Arg(help="Remote name")]

class RemoveCmd(BaseModel):
    action: Literal['remove'] = 'remove'
    name: Annotated[str, Arg(help="Remote name")]

class RemoteCmd(BaseModel):
    action: Literal['remote'] = 'remote'
    sub: Subcommand(AddCmd, RemoveCmd)

class GitCLI(BaseModel):
    command: Subcommand(RemoteCmd, ListCmd)

# Usage: git-tool remote add --name origin
```

## Automatic CLI Generation

### Field Types

Dracon automatically handles various field types:

```python
class Config(BaseModel):
    # String argument
    name: Annotated[str, Arg(help="Application name")]
    
    # Integer with validation
    port: Annotated[int, Arg(help="Port number")] = 8080
    
    # Boolean flag
    debug: Annotated[bool, Arg(help="Enable debug mode")] = False
    
    # Choices from Literal
    log_level: Annotated[
        Literal['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        Arg(help="Logging level")
    ] = 'INFO'
    
    # List argument
    tags: Annotated[List[str], Arg(help="Resource tags")] = []
```

### Nested Models

Nested Pydantic models become grouped arguments:

```python
class DatabaseConfig(BaseModel):
    host: Annotated[str, Arg(help="Database host")] = 'localhost'
    port: Annotated[int, Arg(help="Database port")] = 5432

class AppConfig(BaseModel):
    database: Annotated[DatabaseConfig, Arg(help="Database settings")]
```

CLI usage:
```bash
myapp --database.host db.example.com --database.port 5433
```

### Optional Fields

```python
class Config(BaseModel):
    # Required field (no default)
    api_key: Annotated[str, Arg(help="API authentication key")]
    
    # Optional field (has default)
    timeout: Annotated[int, Arg(help="Request timeout")] = 30
    
    # Optional field (using Optional)
    proxy_url: Annotated[Optional[str], Arg(help="Proxy URL")] = None
```

## Advanced Argument Patterns

### File Loading Arguments

```python
class Config(BaseModel):
    # Automatically loads file content
    secrets: Annotated[dict, Arg(
        is_file=True, 
        help="Secrets configuration file"
    )]
    
    # Manual file loading with validation
    schema: Annotated[str, Arg(help="Schema definition file")]
    # Use: --schema +schema.json
```

### Deferred Arguments

```python
from dracon import DeferredNode

class Config(BaseModel):
    # Computed at runtime
    output_path: Annotated[DeferredNode[str], Arg(
        resolvable=True,
        help="Output directory (supports runtime context)"
    )]
```

### Complex Validation

```python
from pydantic import Field, validator

class Config(BaseModel):
    # With Pydantic validation
    workers: Annotated[int, Arg(help="Worker processes")] = Field(
        default=1, 
        ge=1, 
        le=32,
        description="Number of worker processes (1-32)"
    )
    
    @validator('workers')
    def validate_workers(cls, v):
        if v > os.cpu_count():
            raise ValueError(f"Workers ({v}) exceeds CPU count ({os.cpu_count()})")
        return v
```

## Help Text Generation

### Automatic Help

Dracon automatically generates help text from:

1. `Arg(help=...)` (highest priority)
2. Pydantic `Field(description=...)`
3. Type annotations
4. Default values

```python
class Config(BaseModel):
    # Uses Arg help
    port: Annotated[int, Arg(help="Server port")] = Field(
        default=8080,
        description="Port for HTTP server"  # Ignored
    )
    
    # Falls back to Field description
    timeout: Annotated[int, Field(description="Request timeout")] = 30
    
    # Automatic from type and default
    debug: bool = False  # Shows: --debug (bool, default: False)
```

### Type Information

Help automatically includes:

- Type hints: `int`, `str`, `bool`, etc.
- Literal choices: `'dev', 'staging', or 'prod'`
- Default values: `[default: 8080]`
- Required indicators: `(required)` for fields without defaults

## CLI Usage Patterns

### Standard Arguments

```bash
# Boolean flags (presence sets True)
myapp --debug                    # Sets debug=True

# Value arguments (space or equals syntax)
myapp --port 9090
myapp --port=9090
myapp --environment prod
myapp --environment=prod

# Short flags
myapp -e prod -p 9090
```

### File Loading

```bash
# Config file layering (+ prefix, merged left to right)
myapp +base.yaml +overrides.yaml

# File loading on a specific field
myapp --database +db-config.yaml
myapp --secrets +secrets.json

# File loading with keypath selector (@)
myapp --database +config.yaml@database.production
myapp +full_config.yaml@database           # extract subtree from layered file
```

### Nested Arguments

```bash
# Nested model fields
myapp --database.host db.example.com
myapp --database.port 5433
myapp --database.ssl true

# Multiple nesting levels
myapp --app.database.host localhost
myapp --app.logging.level DEBUG
```

### Variable Definition

```bash
# Define context variables (all equivalent)
myapp ++environment production           # shorthand, space-separated
myapp ++environment=production           # shorthand, equals syntax
myapp --define.environment production    # long form, space-separated
myapp --define.environment=production    # long form, equals syntax

# Values are parsed as YAML
myapp ++count=5                         # int
myapp ++layers="[1, 2, 3]"             # list

# Use in configuration files as ${environment}, ${version}
```

### Advanced Overrides

```bash
# Load config and override specific values
myapp +prod.yaml --workers 16 --database.pool_size 50

# Override with file content
myapp --api_key +secrets/api.key

# Override nested value from file
myapp --database.password +secrets/db-pass.txt
```

## `HelpSection`

Custom sections displayed in CLI `--help` output, between the options and the epilog.

```python
from dracon import HelpSection

@dracon_program(
    name="my-tool",
    sections=[
        HelpSection(title="Examples", body="  my-tool --port 9090 +prod.yaml"),
        HelpSection(title="Environment Variables", body="  DB_HOST    Database hostname\n  DB_PORT    Database port"),
    ],
    epilog="See https://docs.example.com for full documentation.",
)
class Config(BaseModel):
    port: int = 8080
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `title` | `str` | Section heading |
| `body` | `str` | Section content (pre-formatted) |

## `dracon_program` Decorator

Turns a Pydantic `BaseModel` into a CLI program by adding class methods.

```python
@dracon_program(
    name="my-app",
    description="My application",
    version="1.0",
)
class Config(BaseModel):
    port: int = 8080
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | Class name | Program name shown in help |
| `description` | `str` | Class docstring | Description shown in help |
| `version` | `str` | `None` | Version string shown in help |
| `deferred_paths` | `List[str]` | `[]` | KeyPaths to defer during loading |
| `context_types` | `List[type]` | `None` | Types added to context as `{name: type}` |
| `context` | `Dict[str, Any]` | `None` | Additional context dict for interpolation |
| `auto_context` | `bool` | `False` | Capture types from the decorator call site |
| `sections` | `List[HelpSection]` | `None` | Custom help sections |
| `epilog` | `str` | `None` | Text shown at the end of help output |

**Added class methods:**

| Method | Description |
|--------|-------------|
| `.cli(argv=None)` | Parse CLI args (or `sys.argv`) and run |
| `.invoke(*configs, **context_kwargs)` | Run with config file paths and injected context |
| `.from_config(*configs, **context_kwargs)` | Load config without running |
| `.load(config_path, context=None)` | Low-level single-file load |

## `make_program(conf_type, **kwargs)`

Low-level factory that creates a `Program[T]` from a `BaseModel` subclass. Accepts the same keyword arguments as `Program` (`name`, `description`, `version`, `sections`, `epilog`, `default_auto_dash_alias`).

## Best Practices

### Help Text

- Use clear, concise descriptions
- Include valid value ranges or formats
- Mention default behavior
- Use consistent terminology

```python
port: Annotated[int, Arg(help="HTTP server port (1024-65535)")] = 8080
log_file: Annotated[str, Arg(help="Log file path (created if missing)")] = "app.log"
```

### Argument Naming

- Use descriptive names
- Prefer underscores for Python, dashes auto-generated for CLI
- Group related arguments in nested models

```python
class ServerConfig(BaseModel):
    listen_port: Annotated[int, Arg(help="Port to listen on")]
    max_connections: Annotated[int, Arg(help="Maximum concurrent connections")]

class AppConfig(BaseModel):
    server: Annotated[ServerConfig, Arg(help="Server configuration")]
```

### Default Values

- Provide sensible defaults
- Use environment variables for defaults when appropriate
- Document default behavior

```python
workers: Annotated[int, Arg(help="Worker processes")] = Field(
    default_factory=lambda: os.cpu_count(),
    description="Defaults to CPU count"
)
```