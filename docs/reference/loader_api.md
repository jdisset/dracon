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
    trace: bool = True,
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

- **`trace`**: Enable composition tracing. When `True`, the `CompositionResult` returned by `compose()` records where every value came from. Default: `True`. Set to `False` to disable. Also controllable via the `DRACON_TRACE` environment variable.

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

### Composition Tracing

When `trace=True`, `compose()` returns a `CompositionResult` with a `.trace` attribute containing the full provenance of every value.

```python
loader = DraconLoader(trace=True)
cr = loader.compose(['base.yaml', 'prod.yaml'])

# query a single path
history = cr.trace.get("db.port")
# → [TraceEntry(via="definition", value="5432", ...), TraceEntry(via="file_layer", value="5433", ...)]

# query all paths
all_traces = cr.trace_all()
# → {"db.port": [...], "db.host": [...], ...}

# pretty-print
print(cr.trace_tree())
```

Each `TraceEntry` has:

| Field | Type | Description |
|-------|------|-------------|
| `value` | `Any` | The value at this step |
| `source` | `SourceContext \| None` | File, line, column |
| `via` | `ViaKind` | Operation type: `"definition"`, `"file_layer"`, `"include"`, `"merge"`, `"if_branch"`, `"each_expansion"`, `"cli_override"`, etc. |
| `detail` | `str` | Human-readable context (e.g., merge strategy, include path) |
| `replaced` | `TraceEntry \| None` | What this value replaced |

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

### `compose(source, **kwargs)`

Compose a `DeferredNode` with runtime context, returning a `CompositionResult`. This processes composition directives (`!each`, `!if`, `!fn`, `<<:`, etc.) without building Python objects. The result can be passed to `construct()`.

Auto-copies the source DeferredNode to prevent mutation.

```python
composed = dr.compose(config.deferred_field, context={'run_id': 42})
result = dr.construct(composed)
```

### `construct(node_or_val, resolve=True, **kwargs)`

Construct a value into Python objects. Accepts:

- **`DeferredNode`**: Composes and constructs in one step (calls `.construct()` internally).
- **`CompositionResult`**: Constructs from an already-composed result (e.g. output of `compose()`). Uses the attached loader for interpolation resolution.
- **`Node`**: Creates a loader and constructs from raw YAML node.
- **Other values**: Returned as-is.

When `resolve=True` (default), lazy interpolations are resolved after construction.

### `stack(*sources, **ctx)`

Create a `CompositionStack` for runtime-mutable layered composition. Returns a `CompositionStack` initialized with the given sources.

```python
stack = loader.stack("base.yaml", "override.yaml")
stack.push("runtime-patch.yaml")
config = stack.construct()

# undo last layer
stack.pop()

# fork for speculative changes
branch = stack.fork()
branch.push("experimental.yaml")
```

See [CompositionStack](#compositionstack) below.

## CompositionStack

`CompositionStack` is a mutable, ordered layer list with prefix caching. It exposes the merge loop that `compose()` uses internally, letting you push, pop, fork, and reconstruct configurations at runtime.

```python
from dracon import CompositionStack, LayerSpec, LayerScope
```

### Layer Scopes

Each layer has a `scope` controlling what it can see from preceding layers:

| Scope | What later layers see |
|-------|-----------------------|
| `ISOLATED` (default) | Nothing. Each layer composes independently, then merges. |
| `EXPORTS` | `!define`/`!set_default` vars accumulated from preceding layers. |
| `EXPORTS_AND_PREV` | Exported vars + a `PREV` dict containing the previous merged result. |

### LayerSpec

```python
class LayerSpec(BaseModel):
    source: str | Node | CompositionResult  # file path, raw node, or pre-composed result
    context: dict[str, Any] = {}            # per-layer context vars
    merge_key: str = "<<{<+}[<~]"           # merge strategy for this layer
    scope: LayerScope = LayerScope.ISOLATED  # what this layer sees from predecessors
    label: str | None = None                 # trace provenance label
```

### Methods

| Method | Description |
|--------|-------------|
| `push(layer, **ctx)` | Append a layer. Returns the new index. |
| `pop(index=-1)` | Remove a layer. Invalidates cache from that index onward. |
| `replace(index, layer, **ctx)` | Swap a layer in-place (hot-reload). Returns the old layer. |
| `fork()` | Shallow-copy the stack. The fork diverges independently. |
| `composed` (property) | The folded `CompositionResult`, computed incrementally via prefix caching. |
| `construct(**kwargs)` | Compose + construct into Python objects. |

### EXPORTS Scope Example

```python
stack = CompositionStack(loader, [
    LayerSpec(source="base.yaml"),  # has: !define model: resnet
    LayerSpec(source="conditional.yaml", scope=LayerScope.EXPORTS),
])
# conditional.yaml can use ${model} from base.yaml
config = stack.construct()
```

### EXPORTS_AND_PREV Scope Example

```python
stack = CompositionStack(loader, [
    LayerSpec(source="workspace.yaml"),
    LayerSpec(source="add-surface.yaml", scope=LayerScope.EXPORTS_AND_PREV),
])
# add-surface.yaml can use !include var:PREV@surfaces and ${PREV} expressions
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
