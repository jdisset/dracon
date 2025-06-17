# DraconLoader API

The `DraconLoader` class is the core interface for loading and composing configurations in Dracon.

## Constructor

```python
DraconLoader(
    interpolation_engine: Literal['asteval', 'eval', 'none'] = 'asteval',
    enable_shorthand_vars: bool = True,
    deferred_paths: List[KeyPath] = None,
    use_cache: bool = True,
    base_dict_type: Type[dict] = dict,
    base_list_type: Type[list] = list,
    capture_globals: bool = False
)
```

### Parameters

- **`interpolation_engine`**: Controls expression evaluation in `${...}` syntax
  - `'asteval'`: Safe evaluation using asteval (default, recommended)
  - `'eval'`: Native Python eval (faster but potentially unsafe)
  - `'none'`: Disable interpolation entirely

- **`enable_shorthand_vars`**: When `True`, automatically converts `$VAR` to `${VAR}`

- **`deferred_paths`**: List of KeyPath patterns that should be forced to be deferred nodes

- **`use_cache`**: Enable LRU caching of composition results (128 items)

- **`base_dict_type`** / **`base_list_type`**: Custom container types for constructed objects

- **`capture_globals`**: Whether to capture global context during evaluation

## Methods

### `load(sources, context=None, **kwargs)`

Load and compose configuration from one or more sources.

```python
# Load single file
config = loader.load('config.yaml')

# Load multiple files (later files override earlier ones)
config = loader.load(['base.yaml', 'prod.yaml'])

# Provide context for interpolation and Pydantic models
config = loader.load('config.yaml', context={
    'MyModel': MyModel,
    'base_path': '/data'
})
```

### `loads(yaml_string, context=None, **kwargs)`

Load configuration from a YAML string.

```python
yaml_content = """
database:
  host: ${getenv('DB_HOST', 'localhost')}
  port: 5432
"""
config = loader.loads(yaml_content)
```

### `compose(sources, context=None)`

Compose configuration without final construction, returns `CompositionResult`.

```python
result = loader.compose(['base.yaml', 'override.yaml'])
# result.node contains the composed YAML node
# result.context contains the composition context
```

### `merge(left, right, merge_strategy=None)`

Merge two `CompositionResult` objects.

```python
base_result = loader.compose('base.yaml')
override_result = loader.compose('override.yaml')
merged = loader.merge(base_result, override_result, '{>+}')
```

### `dump(obj, **kwargs)`

Serialize an object back to YAML string.

```python
yaml_str = loader.dump(config_object)
```

### `dump_to_node(obj)`

Serialize an object to a YAML node (for advanced use cases).

## Context Variables

When loading files, Dracon automatically provides these context variables:

### File Context (when loading from files)
- `DIR`: Directory containing the current file
- `FILE`: Filename without extension
- `FILE_PATH`: Full file path
- `FILE_STEM`: Filename without extension
- `FILE_EXT`: File extension
- `FILE_LOAD_TIME`: When the file was loaded
- `FILE_SIZE`: File size in bytes

### Built-in Functions
- `getenv(name, default=None)`: Get environment variable
- `getcwd()`: Current working directory
- `listdir(path)`: List directory contents
- `join(*paths)`: Join path components
- `basename(path)`: Get filename from path
- `dirname(path)`: Get directory from path
- `expanduser(path)`: Expand `~` in paths
- `construct(deferred_node, context)`: Construct deferred nodes

## Example Usage

```python
from dracon import DraconLoader
from pydantic import BaseModel

class Config(BaseModel):
    database_url: str
    debug: bool = False

# Create loader with custom settings
loader = DraconLoader(
    interpolation_engine='asteval',
    enable_shorthand_vars=True,
    use_cache=True
)

# Load configuration
config = loader.load(
    ['base.yaml', 'local.yaml'],
    context={'Config': Config}
)

# config is now a validated Config instance
print(config.database_url)
```