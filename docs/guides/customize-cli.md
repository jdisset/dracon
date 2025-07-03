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
- `required`: `True` to mark an optional Pydantic field as required on the CLI. Default derived from Pydantic field definition.
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

## Side Effects During Parsing (`action`)

Execute a function immediately after a specific argument is parsed. Useful for setup tasks like logging.

```python
import logging

def setup_logging(program, value):
  """Action function to configure logging level."""
  level = getattr(logging, value.upper(), logging.INFO)
  logging.basicConfig(level=level)
  print(f"Logging configured to: {value.upper()}")
  # Action functions don't typically modify the config object directly

class LoggingConfig(BaseModel):
    log_level: Annotated[str, Arg(
        short='l',
        action=setup_logging, # Call this function when --log-level is parsed
        help="Set logging level (DEBUG, INFO, WARNING)."
    )] = "INFO"
```

The `action` function receives the `Program` instance and the parsed value for that argument.

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

By combining these `Arg` parameters, you can create sophisticated and user-friendly command-line interfaces directly from your Pydantic configuration models.
