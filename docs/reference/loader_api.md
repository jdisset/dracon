# DraconLoader API

The `DraconLoader` class is the core interface for loading and composing configurations in Dracon.

## Constructor

```python
DraconLoader(
    custom_loaders: Optional[Dict[str, Callable]] = None,
    capture_globals: bool = True,
    base_dict_type: Type = dracontainer.Mapping,
    base_list_type: Type = dracontainer.Sequence,
    enable_interpolation: bool = True,
    interpolation_engine: Literal['asteval', 'eval'] = 'asteval',
    context: Optional[Dict[str, Any]] = None,
    deferred_paths: Optional[List[KeyPath | str]] = None,
    enable_shorthand_vars: bool = True,
    use_cache: bool = True,
)
```

### Parameters

- **`custom_loaders`**: Dictionary mapping scheme names to loader functions. Merged with the built-in loaders (`file`, `pkg`, `env`, `var`). Each loader function receives `(path: str, node=None)` and returns `(content_string, context_dict)`.

- **`capture_globals`**: Whether to capture global context during evaluation. Default: `True`.

- **`base_dict_type`** / **`base_list_type`**: Container types used for constructed objects. Default: `dracontainer.Mapping` / `dracontainer.Sequence` (which support lazy interpolation). Set to `dict` / `list` for plain Python containers.

- **`enable_interpolation`**: Enable `${...}` expression evaluation. Set to `False` to treat interpolation expressions as literal strings. Default: `True`.

- **`interpolation_engine`**: Controls expression evaluation in `${...}` syntax.
  - `'asteval'`: Safe evaluation using asteval (default, recommended)
  - `'eval'`: Native Python eval (faster but potentially unsafe)
  - `'none'` is also accepted at runtime to disable interpolation.

- **`context`**: Initial context dictionary for interpolation. Merged with the built-in default context (see [Built-in Functions](#built-in-functions)).

- **`deferred_paths`**: List of `KeyPath` patterns (or strings) that should be forced into `DeferredNode` instances. Can also be a list of `(KeyPath, Type)` tuples to specify target types.

- **`enable_shorthand_vars`**: When `True`, automatically converts `$VAR` to `${VAR}` during composition. Default: `True`.

- **`use_cache`**: Enable LRU caching of composition results (128 items). Default: `True`.

## Methods

### `load(config_paths, merge_key="<<{<+}[<~]")`

Load and compose configuration from one or more sources. Returns the constructed Python object.

```python
# load single file
config = loader.load('config.yaml')

# load multiple files (later files override earlier ones)
config = loader.load(['base.yaml', 'prod.yaml'])

# custom merge strategy
config = loader.load(['base.yaml', 'prod.yaml'], merge_key='<<{<~}[<~]')
```

**Parameters:**

- `config_paths`: A single path (str or Path) or a list of paths. If a path has no scheme prefix, `file:` is assumed.
- `merge_key`: Dracon merge key string used when merging multiple files. Default: `"<<{<+}[<~]"` (recursive append for dicts, replace for lists, new wins for both).

### `loads(content)`

Load configuration from a YAML string.

```python
yaml_content = """
database:
  host: ${getenv('DB_HOST', 'localhost')}
  port: 5432
"""
config = loader.loads(yaml_content)
```

### `compose(config_paths, merge_key="<<{<+}[<~]")`

Compose configuration without final construction — returns a `CompositionResult` containing the YAML node tree.

```python
result = loader.compose(['base.yaml', 'override.yaml'])
# result.root — the composed YAML root node
# result.defined_vars — variables defined via !define
```

### `merge(comp_res_1, comp_res_2, merge_key)`

Merge two `CompositionResult` objects using a merge strategy.

```python
base_result = loader.compose('base.yaml')
override_result = loader.compose('override.yaml')
merged = loader.merge(base_result, override_result, '<<{>+}')
```

**Parameters:**

- `comp_res_1`: First `CompositionResult`.
- `comp_res_2`: Second `CompositionResult` (or a raw YAML Node).
- `merge_key`: A `MergeKey` object or merge key string (required, no default).

### `dump(data, stream=None)`

Serialize an object to YAML. Returns a string if `stream` is `None`, otherwise writes to the stream.

```python
yaml_str = loader.dump(config_object)

# or write to file
with open('output.yaml', 'w') as f:
    loader.dump(config_object, stream=f)
```

### `update_context(kwargs)`

Merge additional key-value pairs into the loader's interpolation context.

### `copy()`

Create a copy of the loader with the same settings and context.

## Context Variables

When loading files, Dracon automatically provides these context variables:

### File Context (set per-file by the `file:` loader)

| Variable | Description |
|----------|-------------|
| `DIR` | Directory containing the current file |
| `FILE` | Full file path (same as `FILE_PATH`) |
| `FILE_PATH` | Full file path |
| `FILE_STEM` | Filename without extension |
| `FILE_EXT` | File extension (e.g. `.yaml`) |
| `FILE_LOAD_TIME` | Human-readable load timestamp (`YYYY-MM-DD HH:MM:SS`) |
| `FILE_LOAD_TIME_UNIX` | Load time as Unix timestamp (seconds) |
| `FILE_LOAD_TIME_UNIX_MS` | Load time as Unix timestamp (milliseconds) |
| `FILE_SIZE` | File size in bytes |

### Built-in Functions

These are always available in `${...}` expressions:

| Function | Description |
|----------|-------------|
| `getenv(name, default=None)` | Get environment variable |
| `getcwd()` | Current working directory |
| `listdir(path)` | List directory contents |
| `join(*paths)` | Join path components (`os.path.join`) |
| `basename(path)` | Get filename from path (`os.path.basename`) |
| `dirname(path)` | Get directory from path (`os.path.dirname`) |
| `expanduser(path)` | Expand `~` in paths (`os.path.expanduser`) |
| `now(fmt='%Y-%m-%d %H:%M:%S')` | Current datetime formatted as string |
| `construct(deferred_node, **ctx)` | Construct deferred nodes at runtime |

When `numpy` is installed, `np` is also available for use in expressions (e.g. `${np.array([1,2,3])}`).

## Module-Level Functions

These convenience functions create a `DraconLoader` internally:

```python
import dracon as dr

# load from file(s) — **kwargs forwarded to DraconLoader constructor
config = dr.load('config.yaml', context={'MyModel': MyModel})
config = dr.load(['base.yaml', 'prod.yaml'], merge_key='<<{<~}[<~]')

# load from string
config = dr.loads('key: value')

# load single file (convenience)
config = dr.load_file('config.yaml')

# dump to YAML
yaml_str = dr.dump(config_object)
```

## Example Usage

```python
from dracon import DraconLoader
from pydantic import BaseModel

class Config(BaseModel):
    database_url: str
    debug: bool = False

# create loader with custom settings
loader = DraconLoader(
    interpolation_engine='asteval',
    context={'Config': Config},
)

# load configuration
config = loader.load(['base.yaml', 'local.yaml'])

# config is now a validated Config instance
print(config.database_url)
```
