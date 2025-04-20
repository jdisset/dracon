# Loading Configuration

The primary way to interact with Dracon is through the `DraconLoader`. This class handles parsing YAML, processing Dracon's special syntax, and constructing your final Python configuration object. Dracon also provides convenience functions `dracon.load`, `dracon.loads`, and `dracon.dump` for common operations.

## Basic Usage

```python
from dracon import DraconLoader, load, loads, dump

# Simplest way: load from a file path
config_from_file = load("path/to/your/config.yaml")

# Load from a string
yaml_string = '''
key: value
nested:
  level: 1
'''
config_from_string = loads(yaml_string)

# Using the loader directly (offers more configuration)
loader = DraconLoader()
config_explicit = loader.load("path/to/your/config.yaml")
config_explicit_string = loader.loads(yaml_string)

print(config_from_file.some_key)
print(config_from_string.nested.level)

# Dumping back to YAML string
dumped_yaml = dump(config_from_string)
print(dumped_yaml)
```

## Providing Context

Often, you'll need to provide runtime information or helper functions to your configuration files. This is done using the `context` argument when creating a `DraconLoader` or passed to the `load`/`loads` functions. The context is a dictionary available during both the composition and interpolation phases.

```python
# main.py
import os
from dracon import DraconLoader

def generate_id(prefix):
    import uuid
    return f"{prefix}-{uuid.uuid4()}"

context = {
    'ENV': os.getenv('ENVIRONMENT', 'development'),
    'INSTANCE_ID': 42,
    'generate_id': generate_id # Make function available
}

loader = DraconLoader(context=context, enable_interpolation=True) # Enable interpolation
config = loader.load("app_config.yaml")

# Alternatively using the convenience function:
# config = load("app_config.yaml", context=context, enable_interpolation=True)

print(config.service_id)
```

```yaml
# app_config.yaml
environment: ${ENV} # Uses ENV from context
server_port: ${8000 + INSTANCE_ID} # Uses INSTANCE_ID and calculation
service_id: ${generate_id(ENV)} # Call the function from context
```

### Default Context

Dracon automatically adds a few useful items to the context by default:

- `getenv`: Equivalent to `os.getenv`.
- `getcwd`: Equivalent to `os.getcwd`.
- `construct`: A function to manually trigger construction of nodes (useful within `${...}` for complex object interactions).

## Loading from Different Sources

While `loader.load("path/to/file.yaml")` implicitly uses the `file:` loader if no prefix is given, you can be explicit using loader prefixes within include directives (`!include prefix:path`) or aliases (`*prefix:path`). See [Includes](includes.md).

Dracon comes with built-in loaders:

- `file:`: Loads from the filesystem relative to the current file or working directory.
  ```yaml
  settings: !include file:./settings.yaml
  # Use shorthand for file includes if no prefix given
  credentials: !include /etc/secrets.conf # Absolute path interpreted as file:
  ```
- `pkg:`: Loads from installed Python package resources. Requires `package_name:path/to/resource.yaml`.
  ```yaml
  defaults: !include pkg:my_package:configs/defaults.yaml
  base_settings: *pkg:common_lib:base.yaml # Using an alias
  ```
- `env:`: Loads a value directly from an environment variable.
  ```yaml
  api_key: !include env:API_KEY
  secret: *env:APP_SECRET
  ```
  !!! note
  Using `!include env:VAR` fetches the variable during the _composition_ phase. Using `${getenv('VAR')}` fetches it during _interpolation_ (runtime/lazy evaluation by default).

## Custom Loaders

You can extend Dracon to load configurations from other sources (databases, APIs, etc.) by providing custom loader functions.

```python
import redis
from dracon import DraconLoader
from typing import Optional # Needed for type hint

def load_from_redis(path: str, loader: Optional[DraconLoader] = None):
    # path is the string after 'redis:'
    r = redis.Redis(decode_responses=True)
    key = path
    value = r.get(key)
    if value is None:
        raise FileNotFoundError(f"Redis key '{key}' not found.")
    # Custom loaders should return the raw content (string)
    # and optionally a dictionary of context variables to add.
    # Context variables starting with '$' are useful (e.g., $REDIS_KEY).
    return value, {'$REDIS_KEY': key}

# Register the custom loader
loader = DraconLoader(custom_loaders={'redis': load_from_redis})

# Now you can use it in YAML
# config: !include redis:my_app:settings
```

## Error Handling

- **FileNotFoundError:** Raised if an included file (via `file:` or `pkg:`) cannot be found.
- **ValueError:** Raised for invalid syntax (e.g., unknown loader, malformed include string, invalid merge key).
- **DraconError / InterpolationError:** Raised during `${...}` or `$(...)` evaluation if an expression is invalid, references are broken, or context is missing.
- **ValidationError (Pydantic):** Raised if the final constructed object fails Pydantic model validation when using type tags.

## Caching

By default (`use_cache=True`), Dracon caches the raw content fetched by `file:` and `pkg:` loaders to speed up loading of frequently included files. Set `use_cache=False` in the `DraconLoader` constructor to disable this.

## Output Types

By default, Dracon constructs mappings into `dracon.dracontainer.Mapping` and sequences into `dracon.dracontainer.Sequence`. These custom types handle lazy interpolation resolution automatically when attributes or items are accessed.

You can instruct the loader to use standard Python `dict` and `list` instead:

```python
from dracon import DraconLoader

# Use standard Python dicts and lists
loader = DraconLoader(base_dict_type=dict, base_list_type=list)
config = loader.load("config.yaml")

assert isinstance(config, dict)
# Note: With standard types, lazy interpolation needs manual triggering
# if not accessed directly. See Interpolation documentation.
```
