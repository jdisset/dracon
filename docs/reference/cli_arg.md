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

### `action: str`
Custom argument action (passed to argparse).

```python
verbose: Annotated[int, Arg(action='count', help="Verbosity level")]
# Creates: -v, -vv, -vvv for increasing verbosity
```

### `default_str: str`
Custom default value representation in help.

```python
workers: Annotated[int, Arg(
    default_str="CPU count",
    help="Number of worker processes"
)] = None  # Actual default computed later
```

### `auto_dash_alias: bool = True`
Automatically create dash-separated aliases for underscore fields.

```python
max_connections: Annotated[int, Arg(help="Maximum connections")]
# Creates both --max_connections and --max-connections
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
# Boolean flags
myapp --debug                    # Sets debug=True
myapp --no-debug                 # Sets debug=False

# Value arguments
myapp --port 9090
myapp --environment prod

# Short flags
myapp -e prod -p 9090
```

### File Loading

```bash
# Explicit file loading (+ prefix)
myapp +config.yaml
myapp --database +db-config.yaml
myapp --secrets +secrets.json

# File loading with keypath
myapp --database +config.yaml@database.production
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
# Define context variables
myapp --define.environment production
myapp --define.version 1.2.3

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