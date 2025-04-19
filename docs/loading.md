# Loading Configuration

The primary way to interact with Dracon is through the `DraconLoader`. This class handles parsing YAML, processing Dracon's special syntax, and constructing your final Python configuration object.
Dracon also provides a `load` function for convenience, which is a shortcut to create a `DraconLoader` instance and load a configuration file in one step.

## Basic Usage

```python
from dracon import load

config = load("path/to/your/config.yaml")

# Load from a string
yaml_string = '''
key: value
nested:
  level: 1
'''
config_from_string = loads(yaml_string)

print(config.some_key)
print(config_from_string.nested.level)
```

## Providing Context

Often, you'll need to provide runtime information or helper functions to your configuration files. This is done using the `context` argument. The context is a dictionary available during both the composition and interpolation phases.

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

loader = DraconLoader(context=context)
config = loader.load("app_config.yaml")

print(config.service_id)
```

```yaml
# app_config.yaml
environment: ${ENV}
server_port: ${8000 + INSTANCE_ID}
service_id: ${generate_id(ENV)} # Call the function from context
```

### Default Context

Dracon automatically adds a few useful items to the context:

- `getenv`: Equivalent to `os.getenv`.
- `getcwd`: Equivalent to `os.getcwd`.
- `construct`: A function to manually trigger construction of nodes (useful within `${...}`).

## Loading from Different Sources

While `loader.load("path/to/file.yaml")` implicitly uses the `file:` loader, you can be explicit using loader prefixes within include directives (see [Includes](includes.md)).

Dracon comes with built-in loaders:

- `file:`: Loads from the filesystem relative to the current file or working directory.
  ```yaml
  settings: !include file:./settings.yaml
  credentials: *file:/etc/secrets.conf # Absolute path
  ```
- `pkg:`: Loads from installed Python package resources. Requires `package_name:path/to/resource.yaml`.
  ```yaml
  defaults: !include pkg:my_package:configs/defaults.yaml
  base_settings: *pkg:common_lib:base.yaml
  ```
- `env:`: Loads a value directly from an environment variable.
  ```yaml
  api_key: !include env:API_KEY
  secret: *env:APP_SECRET
  ```
  !!! note
  Using `!include env:VAR` fetches the variable during the _composition_ phase. Using `${getenv('VAR')}` fetches it during _interpolation_ (runtime/lazy evaluation).

## Custom Loaders

You can extend Dracon to load configurations from other sources (databases, APIs, etc.) by providing custom loader functions.

```python
import redis
from dracon import DraconLoader

def load_from_redis(path: str):
    # path is the string after 'redis:'
    r = redis.Redis(decode_responses=True)
    key = path
    value = r.get(key)
    if value is None:
        raise FileNotFoundError(f"Redis key '{key}' not found.")
    # Custom loaders should return the raw content (string)
    # and optionally a dictionary of context variables to add.
    return value, {'$REDIS_KEY': key}

# Register the custom loader
loader = DraconLoader(custom_loaders={'redis': load_from_redis})

# Now you can use it in YAML
# config: !include redis:my_app:settings
```

## Error Handling

- **FileNotFoundError:** Raised if an included file (via `file:` or `pkg:`) cannot be found.
- **ValueError:** Raised for invalid syntax (e.g., unknown loader, malformed include string).
- **InterpolationError:** Raised during `${...}` evaluation if an expression is invalid or references are broken.
- **ValidationError (Pydantic):** Raised if the final constructed object fails Pydantic model validation.

## Caching

By default (`use_cache=True`), Dracon caches the raw content fetched by `file:` and `pkg:` loaders to speed up loading of frequently included files. Set `use_cache=False` to disable this.

## Output Types

By default, Dracon constructs mappings into `dracon.dracontainer.Mapping` and sequences into `dracon.dracontainer.Sequence`. These custom types handle lazy interpolation resolution automatically.

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
