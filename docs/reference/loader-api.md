# Loader API

## DraconLoader

The main entry point for loading and composing configurations.

```python
from dracon import DraconLoader
```

### Constructor

```python
DraconLoader(
    custom_loaders: Dict[str, Callable] = None,
    capture_globals: bool = True,
    base_dict_type: Type[DictLike] = dracontainer.Mapping,
    base_list_type: Type[ListLike] = dracontainer.Sequence,
    enable_interpolation: bool = True,
    interpolation_engine: Literal['asteval', 'eval'] = 'asteval',
    context: Dict[str, Any] = None,
    deferred_paths: list[KeyPath | str] = None,
    enable_shorthand_vars: bool = True,
    use_cache: bool = True,
    trace: bool = True,
)
```

| Parameter | Description |
|-----------|-------------|
| `custom_loaders` | Scheme-to-loader mappings, merged on top of built-in loaders (`file`, `pkg`, `env`, `var`, `raw`, `rawpkg`, `cascade`). |
| `capture_globals` | Whether to capture global variables into context. |
| `base_dict_type` | Container type for mappings. Default `dracontainer.Mapping` (a dict-like with metadata support). Use `dict` for plain output. |
| `base_list_type` | Container type for sequences. Default `dracontainer.Sequence`. Use `list` for plain output. |
| `enable_interpolation` | Enable `${...}` expression evaluation. When `False`, interpolation strings are kept as literals. |
| `interpolation_engine` | `'asteval'` (safe sandbox, default) or `'eval'` (full Python eval, unsafe). |
| `context` | Initial interpolation context. Keys become variables available in `${...}` expressions. |
| `deferred_paths` | List of keypaths (strings or `KeyPath` objects) that are forced to `DeferredNode` during composition. Supports wildcards. |
| `enable_shorthand_vars` | When `True`, bare `$VAR` tokens are converted to `${VAR}` before interpolation. |
| `use_cache` | LRU cache (128 items) for parsed YAML strings. Disable for mutation-heavy workflows. |
| `trace` | Enable composition tracing. Also enabled when `DRACON_TRACE=1` is set. |

### Methods

#### `load(config_paths, merge_key="<<{<+}[<~]")`

Load configuration from one or more file paths. Multiple paths are merged left to right.

Returns the fully constructed Python object (dict, Pydantic model, etc.).

```python
loader = DraconLoader()
config = loader.load("file:config.yaml")
config = loader.load(["base.yaml", "overrides.yaml"])
```

#### `loads(content: str)`

Load configuration from a YAML string.

```python
config = loader.loads("key: ${1 + 2}")
```

#### `compose(config_paths, merge_key="<<{<+}[<~]")`

Compose without constructing. Returns a `CompositionResult` (the raw YAML node tree after all includes, merges, and instructions have been processed).

```python
cr = loader.compose("config.yaml")
# inspect cr.root, cr.defined_vars, cr.trace, etc.
obj = loader.load_node(cr.root)
```

#### `merge(cr1, cr2, merge_key)`

Merge two `CompositionResult` objects using a merge key string.

```python
cr_merged = loader.merge(cr1, cr2, "<<{<+}[<~]")
```

#### `dump(data, stream=None)`

Serialize data back to YAML. Returns a string if `stream` is `None`, otherwise writes to the stream.

#### `update_context(kwargs: dict)`

Add entries to the loader's interpolation context.

#### `copy()`

Create a shallow copy of the loader with independent context. Useful for isolated operations.

#### `stack(*sources, **ctx)`

Create a `CompositionStack` from source strings/specs. Context kwargs are applied to the first layer.

```python
stack = loader.stack("base.yaml", "overrides.yaml", env="prod")
result = stack.construct()
```

---

## Module-level Functions

These are convenience wrappers that create a `DraconLoader` internally.

```python
import dracon
```

### `dracon.load(config_paths, raw_dict=False, merge_key="<<{<+}[<~]", **kwargs)`

Load one or more config files. Pass `raw_dict=True` to get plain Python dicts/lists instead of Dracontainers. Extra `**kwargs` go to the `DraconLoader` constructor.

### `dracon.loads(config_str, raw_dict=False, **kwargs)`

Load from a YAML string.

### `dracon.load_file(config_path, raw_dict=True, **kwargs)`

Load a single file. Adds `file:` prefix if no scheme is present. Defaults to `raw_dict=True`.

### `dracon.dump(data, stream=None, **kwargs)`

Serialize to YAML.

### `dracon.compose(source, **kwargs)`

Compose a `DeferredNode` with runtime context. Returns a `CompositionResult`.

```python
result = dracon.compose(deferred_node, context={"key": "value"})
```

### `dracon.construct(node_or_val, resolve=True, **kwargs)`

Construct a `DeferredNode`, `CompositionResult`, or raw YAML `Node` into a Python object. When `resolve=True`, also resolves all lazy interpolables.

### `dracon.resolve_all_lazy(obj, permissive=False)`

Walk a constructed object and resolve any remaining `LazyInterpolable` values. When `permissive=True`, unresolvable expressions are left as strings instead of raising.

### `dracon.make_callable(path_or_node, context=None, context_types=None, auto_context=False, **loader_kwargs)`

Turn a YAML config file or `DeferredNode` into a callable function. See [CLI API](cli-api.md) for details.

---

## CompositionStack

Layered composition with per-layer context, merge strategy, and scope control.

```python
from dracon import CompositionStack, LayerSpec, LayerScope
```

### LayerSpec

```python
LayerSpec(
    source: str | Node | CompositionResult,
    context: dict[str, Any] = {},
    merge_key: str = "<<{<+}[<~]",
    scope: LayerScope = LayerScope.ISOLATED,
    label: str | None = None,
)
```

### LayerScope

| Value | Receives exports | Receives PREV |
|-------|-----------------|---------------|
| `LayerScope.ISOLATED` | No | No |
| `LayerScope.EXPORTS` | Yes | No |
| `LayerScope.EXPORTS_AND_PREV` | Yes | Yes |

Exports are `!define`d variables from earlier layers. `PREV` is a constructed snapshot of the previous layer's output, available as `${PREV}`.

### Methods

| Method | Description |
|--------|-------------|
| `push(layer, **ctx)` | Append a layer. Returns the layer index. |
| `pop(index=-1)` | Remove and return a layer. Invalidates cache from that point. |
| `replace(index, layer, **ctx)` | Replace a layer in-place. Invalidates cache from that point. |
| `fork()` | Create an independent copy sharing cached prefix. |
| `composed` | Property. Returns the fully composed `CompositionResult`. |
| `construct(**kwargs)` | Compose, then construct. Extra kwargs update loader context. |
| `layers` | Property. The list of `LayerSpec` objects. |

---

## Composition Tracing

Opt-in provenance tracking. Records how each leaf value arrived at its final state.

Enable via `trace=True` in `DraconLoader` or `DRACON_TRACE=1` environment variable.

### TraceEntry

```python
@dataclass
class TraceEntry:
    value: Any               # the value at this step
    source: SourceContext     # file/line/column
    via: ViaKind              # how the value arrived
    detail: str = ""          # human-readable context
    replaced: TraceEntry = None  # previous entry (linked list)
```

### ViaKind

Literal union of: `"definition"`, `"file_layer"`, `"include"`, `"merge"`, `"if_branch"`, `"each_expansion"`, `"cli_override"`, `"set_default"`, `"define"`, `"context_variable"`.

### CompositionTrace

| Method | Description |
|--------|-------------|
| `record(path, entry)` | Record an entry. Auto-links `replaced` to previous. |
| `get(path) -> list[TraceEntry]` | Get history for a dotted path. |
| `all() -> dict` | All entries. |
| `format_path(path) -> str` | Plain-text trace for one path. |
| `format_all() -> str` | Plain-text full provenance tree. |
| `format_path_rich(path)` | Rich `Panel` for one path. |
| `format_all_rich()` | Rich `Table` of all entries. |

---

## Built-in Context

Every interpolation gets these functions and variables by default.

### Functions

| Name | Wraps |
|------|-------|
| `getenv(name, default=None)` | `os.getenv` |
| `getcwd()` | `os.getcwd` |
| `listdir(path)` | `os.listdir` |
| `join(*parts)` | `os.path.join` |
| `basename(path)` | `os.path.basename` |
| `dirname(path)` | `os.path.dirname` |
| `expanduser(path)` | `os.path.expanduser` |
| `isfile(path)` | `os.path.isfile` |
| `isdir(path)` | `os.path.isdir` |
| `Path` | `pathlib.Path` |
| `now(fmt='%Y-%m-%d %H:%M:%S')` | `datetime.now().strftime(fmt)` |
| `construct(node, ...)` | `dracon.construct` (bound to current loader settings) |

### File Context Variables

Set automatically when loading from a file:

| Variable | Example value |
|----------|---------------|
| `DIR` | `/home/user/project` |
| `FILE` | `/home/user/project/config.yaml` |
| `FILE_PATH` | Same as `FILE` |
| `FILE_STEM` | `config` |
| `FILE_EXT` | `.yaml` |
| `FILE_LOAD_TIME` | `2025-01-15 14:30:00` |
| `FILE_LOAD_TIME_UNIX` | `1736952600` |
| `FILE_LOAD_TIME_UNIX_MS` | `1736952600000` |
| `FILE_SIZE` | `1234` (bytes) |
