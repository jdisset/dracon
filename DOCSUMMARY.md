# Dracon: The Engineer's Manual

**Dracon** is a configuration engine that strictly separates **Composition** (YAML graph manipulation) from **Construction** (Python object instantiation). It creates a programmable configuration layer before your application logic ever sees the data.

## 1. The Core Lifecycle

1.  **Composition:** Raw text is parsed. Instructions (`!if`, `!define`) modify the tree. Includes are resolved recursively. Merges (`<<:`) are applied.
2.  **Construction:** The final node tree is traversed. Python objects (Pydantic models, primitives) are instantiated.
3.  **Resolution:** Interpolations (`${...}`) are wrapped in `LazyInterpolable`. They evaluate **only upon access**.

## 2. Python API

### 2.1. Loading

```python
from dracon import load, loads, dump, compose, construct, DraconLoader

# 1. Simple Load
cfg = load(["base.yaml", "override.yaml"], context={"MyModel": MyModel})

# 2. Advanced Loader
loader = DraconLoader(
    context={"func": my_func},          # Available in ${...} and !Tags
    interpolation_engine='asteval',     # 'asteval' (safe) or 'eval' (unsafe)
    deferred_paths=['/secrets/**'],     # Force paths to be DeferredNodes
    enable_shorthand_vars=True,         # Allow $VAR alongside ${VAR}
    trace=True,                         # Composition tracing (default: True)
)
cfg = loader.load("config.yaml")

# 3. Composition Only (Inspect the graph before construction)
comp_result = loader.compose("config.yaml") # Returns CompositionResult

# 4. Merge two CompositionResults
merged = loader.merge(comp_res_1, comp_res_2, merge_key="<<{<+}[<~]")

# 5. CompositionStack: mutable layered composition
stack = loader.stack("base.yaml", "override.yaml")
stack.push("runtime-patch.yaml")     # extend
config = stack.construct()           # compose + construct
stack.pop()                          # undo last layer
branch = stack.fork()                # speculative branch

# 6. Two-step deferred: compose then construct separately
composed = compose(cfg.deferred_field, context={"run_id": 42})
result = construct(composed)
```

### 2.2. Return Types

- **Default:** `Dracontainer` (Smart `Mapping`/`Sequence`). Resolves lazy values on access (`cfg.key`).
- **Raw:** `load(..., raw_dict=True)`. Returns standard `dict`. Lazy values remain `LazyInterpolable`. Use `dracon.resolve_all_lazy(obj)` to force evaluation.

### 2.3. Serialization (Dumping)

Dracon supports round-tripping, preserving tags and structure where possible.

```python
yaml_str = dump(config_object)
```

Classes can implement the `DraconDumpable` protocol (`dracon_dump_to_node(self, representer)`) to customize their YAML representation.

## 3. Composition Instructions (`!tags`)

Executed during Phase 1. Modifications apply to the YAML graph.

### 3.1. Variable Definition

Defines variables in the current scope's context. These are removed from the final configuration tree.

- **`!define key: value`**: Sets `key` in the context. For expressions (`${...}`), evaluated immediately. For **typed objects** (`!MyModel { ... }`), construction is **lazy** -- happens on first `${key}` access, enabling forward references and pipeline-style YAML.
- **`!set_default key: value`**: Sets `key` only if it doesn't exist in the context (useful in included files). Also supports lazy construction for typed objects.

**Construction timing gradient:**

| Pattern | Resolves | Use case |
|---------|----------|----------|
| `!define x: 42` | Immediately (literal) | Constants, simple values |
| `!define x: ${expr}` | Composition time (expression) | Derived strings, comprehensions |
| `!define x: !Type { ... }` | On first `${x}` access (lazy) | Pipeline stages, Python objects |
| `!define f: !fn ...` | On each `f(...)` call | Reusable templates with args |
| `!define p: !pipe [...]` | On each `p(...)` call | Composed pipeline of callables |
| `!fn:path { kwargs }` | Construction time (once) | Serializable partial application |
| `!deferred` | Runtime (manual `.construct()`) | Objects needing live runtime state |

**Lazy `!define` replaces** the old `!noconstruct` + `construct(&/ref)` ceremony:

```yaml
# old way:
!noconstruct data: !DataLoader
  path: ${data_path}
!define result: ${construct(&/data).process()}

# new way:
!define data: !DataLoader
  path: ${data_path}
!define result: ${data.process()}
```

Key behaviors: result is the real Python object (not a proxy), construction is cached (at most once), forward references work, circular references are detected, unreferenced objects are never constructed.

### 3.2. Conditionals (`!if`)

Conditionally includes or removes nodes based on an expression.

- **Syntax A (Shorthand):** `!if ${expr}: { content }`. If true, content is merged/included. If false, node is removed.
- **Syntax B (Block):** Explicit branches.
  ```yaml
  !if ${env == 'prod'}:
    then: { retries: 5 }
    else: { retries: 1 }
  ```

### 3.3. Iteration (`!each`)

Generates nodes by iterating over a list or dictionary.

- **Syntax:** `!each(var_name) ${iterable}: <template>`
- **Lists:** Duplicates the template for each item, appending to the parent list.
- **Maps:** Merges the generated nodes into the parent map.
  - _Critical:_ Keys _must_ be dynamic (interpolated) to avoid collision.
  - _Tuple Unpacking:_ The regex captures one variable. If iterating `dict.items()`, `${var}` is a tuple `(k, v)`. Access via `${var[0]}` and `${var[1]}`.

#### Inline Sequence Expansion (Auto-Splice)

When `!each` appears as an item in a sequence and produces a sequence, items are **spliced inline** rather than nested:

```yaml
!define services: [svc1, svc2]

tasks:
  - name: setup                    # Static item
  - !each(s) ${services}:          # Dynamic items spliced inline
      - name: deploy_${s}
  - name: cleanup                  # Static item

# Result: [{name: setup}, {name: deploy_svc1}, {name: deploy_svc2}, {name: cleanup}]
```

This enables mixing static and dynamic items in a single sequence without explicit concatenation.

### 3.4. Callable Templates (`!fn`)

`!fn` wraps a YAML template into a callable. Three forms:

```yaml
# from a file
!define make_endpoint: !fn file:templates/endpoint.yaml

# inline mapping -- returns the mapping
!define greet: !fn
  !require who: "name"
  msg: hello ${who}

# inline scalar (expression lambda)
!define double: !fn ${x * 2}
```

**Scalar return with `!fn :`:** Use `!fn :` inside the body to return a single value instead of the full mapping. The outer `!fn` tag is optional when `!fn :` is present:

```yaml
!define double:
  !require x: "number"
  !fn : ${x * 2}

result: ${double(x=21)}  # => 42
```

**Invocation:** Tag syntax or expression syntax:

```yaml
api: !make_endpoint { name: api, port: 443 }
all: ${[make_endpoint(name=n) for n in service_names]}
greeting: ${greet(who='world')}
```

**Tag invocation for any callable:** Any non-type callable in context works as a YAML tag -- not just `!fn` templates. Python functions, lambdas, etc. With a mapping, kwargs are unpacked. With a scalar, it's passed as a single positional arg.

```yaml
# Python function from context
result: !make_url { host: example.com, port: 443 }
greeting: !upper "hello"
```

- Parameters: `!require` (mandatory) and `!set_default` (optional) inside the template.
- Isolation: each call gets a fresh scope; args don't leak into the caller.
- The template body is full dracon (`!if`, `!each`, `!include`, type tags all work).

### 3.5. Partial Application (`!fn:path`)

`!fn:path` wraps a Python function with pre-filled kwargs, producing a `DraconPartial`. Unlike `!fn` (which wraps a YAML template), `!fn:path` wraps a real Python callable resolved by import path or context lookup.

```yaml
loss_fn: !fn:biocomp.train.energy_loss
  kl_weight: !optax.polynomial_schedule { init_value: 0.1 }
  energy_weight: 0.5

# zero-arg form: serializable function reference
activation: !fn:jax.nn.relu
```

Calling `loss_fn(stack, config)` invokes `energy_loss(stack, config, kl_weight=<schedule>, energy_weight=0.5)`. Runtime kwargs override stored ones.

Key differences from `!fn`: kwargs are resolved once at construction (not re-composed each call), the result is serializable (pickle + YAML round-trip), and it wraps a Python function, not a YAML template.

The path resolves in context first, then as a dotted import. Nested tags and `${...}` in the kwargs body are resolved during construction. Works inline in `!pipe` stages:

```yaml
!define pipeline: !pipe
  - !fn:preprocess.load_data
  - !fn:preprocess.clean { strategy: aggressive }
  - !fn:models.train
```

### 3.6. Function Composition (`!pipe`)

`!pipe` takes a sequence of callables and produces a new callable that chains them. The output of each stage feeds as input to the next.

```yaml
!define load: !fn file:templates/load.yaml
!define clean: !fn file:templates/clean.yaml
!define train: !fn file:templates/train.yaml

!define ml: !pipe [load, clean, train]

# call it like any callable
result: !ml { path: /data/train.csv, model_type: xgb }
result: ${ml(path='/data/train.csv', model_type='xgb')}
```

**Output threading:**

- If a stage returns a mapping (dict), it is **kwarg-unpacked** into the next stage. Keys become named arguments.
- If a stage returns a typed object (Pydantic model, etc.), it is passed as a single value to the next stage's one unfilled `!require` parameter.

**Partial application:** Pre-fill kwargs per stage with `name: {kwargs}` syntax:

```yaml
!define ml: !pipe
  - load
  - clean: { strategy: aggressive }   # baked-in default
  - train
```

**Pipeline kwargs** flow through to all stages. `!set_default` params from any stage are available at pipeline call time:

```yaml
!define ml: !pipe [load, clean, train]
# clean has !set_default strategy: standard, train has !set_default epochs: 100
result: ${ml(path='/data/file.csv', strategy='aggressive', epochs=200)}
```

**Composition:** Pipes are callables, so they compose with other pipes:

```yaml
!define preprocess: !pipe [load, clean]
!define train_eval: !pipe [train, evaluate]
!define full: !pipe [preprocess, train_eval]   # flattened into 4 stages
```

### 3.7. Construction Control

- **`!noconstruct`**: The node is processed (anchors/defines are valid) but the node is removed before the Construction phase. **Note:** The common `!noconstruct` + `construct(&/ref)` pattern for building Python objects is now obsolete -- use `!define x: !Type { ... }` with lazy construction instead. Still useful for template anchors and metadata nodes.
- **`__dracon__` Prefix**: Any key starting with `__dracon__` is treated as `!noconstruct`.

## 4. CompositionStack (Runtime Layer Composition)

`CompositionStack` is the ordered layer list that `load([a, b, c])` already builds, made explicit and mutable. The SSOT is the layer list; `composed` is a cached left-fold over it.

```python
from dracon import CompositionStack, LayerSpec, LayerScope
```

### 4.1. API

| Method | Description |
|--------|-------------|
| `push(layer, **ctx)` | Append a layer (string path or `LayerSpec`). Returns index. |
| `pop(index=-1)` | Remove layer, invalidate cache from that point. |
| `replace(index, layer)` | Swap layer in-place (hot-reload). |
| `fork()` | Shallow-copy; fork diverges independently. |
| `composed` | Property: the folded `CompositionResult` (prefix-cached). |
| `construct(**kwargs)` | Compose + construct into Python objects. |

### 4.2. Layer Scopes

| Scope | What later layers see |
|-------|-----------------------|
| `ISOLATED` (default) | Nothing. Same as `load([a, b, c])`. |
| `EXPORTS` | `!define`/`!set_default` vars from preceding layers. Hard/soft priority preserved. |
| `EXPORTS_AND_PREV` | Exports + `PREV` dict (the previous merged result). Enables `${PREV.key}` and `!include var:PREV@path`. |

### 4.3. Example

```python
stack = loader.stack("base.yaml")
stack.push(LayerSpec(source="ml.yaml", scope=LayerScope.EXPORTS))
# ml.yaml can use ${model} defined in base.yaml

stack.push(LayerSpec(source="patch.yaml", scope=LayerScope.EXPORTS_AND_PREV))
# patch.yaml can read PREV to inspect accumulated state

config = stack.construct()
stack.pop()                          # undo patch
branch = stack.fork()                # speculative branch
branch.push("experimental.yaml")
```

## 5. The Merge Operator (`<<:`)

Dracon extends the standard YAML merge key (`<<:`) to provide precise control over combination logic.

**Syntax:** `<<{DICT_OPTS}[LIST_OPTS]@TARGET_PATH: <source>`

### 5.1. Dictionary Strategy `{MODE/PRIORITY}`

- **Mode:**
  - `+` (**Append/Recurse**): Default. Merges keys. If values are dicts, recurses.
  - `~` (**Replace**): If key exists, overwrites value entirely (no recursion).
- **Priority:**
  - `>` (**Existing Wins**): Default. Current node keeps its value on conflict.
  - `<` (**New Wins**): Source node overwrites current node on conflict.
- **Depth:** e.g., `{+2}` limits recursion to 2 levels.

### 5.2. List Strategy `[MODE/PRIORITY]`

- **Mode:** `~` (**Replace**, Default) or `+` (**Concatenate**).
- **Priority:** `>` (**Existing First**, Default) or `<` (**New First**).

### 5.3. Context Propagation

- `(<)` in the merge key propagates the source's context variables upward to the parent. Only works with `<` priority.

### 5.4. Examples

| Syntax     | Semantics  | Use Case                                                     |
| :--------- | :--------- | :----------------------------------------------------------- |
| `<<: *ref` | `{+>}[~>]` | Standard YAML. Recurse dicts (keep existing), Replace lists. |
| `<<{<+}:`  | `{<+}[~>]` | **Override**. Recurse dicts, new values overwrite old.       |
| `<<[+]:`   | `{+>}[+>]` | **Append**. Add items to end of lists.                       |
| `<<[+<]:`  | `{+>}[+<]` | **Prepend**. Add items to start of lists.                    |
| `<<@db:`   | `{<+}`     | Merge source into the `db` sub-key.                          |

## 6. Includes & Loaders

Inject external content at the current node.
**Syntax:** `!include <scheme>:<path>@<selector>`

### 6.1. Schemes

- **`file:`** (Default): Filesystem. Context adds `$DIR`, `$FILE`, `$FILE_STEM`, `$FILE_PATH`, `$FILE_EXT`, `$FILE_SIZE`, `$FILE_LOAD_TIME_UNIX`.
- **`pkg:`**: Python resources (`pkg:package_name:path/inside/package.yaml`). Context adds `$PACKAGE_NAME`.
- **`env:`**: Environment variable string.
- **`var:`**: Dracon context variable (in-memory node).
- **`raw:`**: Load file as plain text string (bypasses YAML parsing). `raw:/path/to/file.txt`.
- **`rawpkg:`**: Load package resource as plain text. `rawpkg:package_name:file.txt`.
- **`cascade:`**: Walk up from CWD (or resolved path) collecting all matching files, merge root-first (closest wins). `cascade:config.yaml`. Supports optional merge key prefix: `cascade:{>+}[>~]:config.yaml`. Use `${DIR}` to start from the current file's directory.
- **Custom:** Register via `custom_loaders` in `DraconLoader`.

### 6.2. Optional Includes

`!include?` is a soft include that silently produces nothing if the file is missing (instead of erroring):

```yaml
<<: !include? file:local_overrides.yaml  # no error if file doesn't exist
```

### 6.3. Selectors (`@`)

Select a specific subtree from the target. Uses KeyPath syntax.

- `!include file:conf.yaml@database.connections.0`

## 7. Interpolation & References

Expressions are strings enclosed in `${...}` (Runtime/Lazy) or `$(...)` (Parse-time/Immediate).

### 7.1. Reference Operators

- **`@path` (Value Reference)**: Retrieves the **final constructed value** at the given KeyPath.
  - Example: `url: "http://${@/server.host}"`.
- **`&path` (Node Copy)**: Retrieves the **raw YAML node** at composition time. Performs a **deep copy**.
  - Example: `new_obj: ${&/templates.base_obj}`.
  - _Parameterized copy:_ `${&/template:var=value}` copies and rebinds context variables.

### 7.2. KeyPath Syntax

Used in `@` references, `@` merges, include selectors, and API calls.

- Separator: `.`. Root: `/`. Escape: `\.`. Wildcards: `*` (matching only).

### 7.3. Default Expression Context

These are available in all `${...}` expressions without explicit definition:

| Function | Source |
|----------|--------|
| `getenv(name)` | `os.getenv` |
| `getcwd()` | `os.getcwd` |
| `listdir(path)` | `os.listdir` |
| `join(a, b, ...)` | `os.path.join` |
| `basename(path)` | `os.path.basename` |
| `dirname(path)` | `os.path.dirname` |
| `expanduser(path)` | `os.path.expanduser` |
| `isfile(path)` | `os.path.isfile` |
| `isdir(path)` | `os.path.isdir` |
| `Path(...)` | `pathlib.Path` |
| `now(fmt)` | `datetime.now().strftime(fmt)` |

Additionally, file loaders inject `$DIR`, `$FILE`, `$FILE_PATH`, `$FILE_EXT`, `$FILE_SIZE`, `$FILE_LOAD_TIME_UNIX` for the current file.

## 8. Tags & Type Resolution

- **Context:** `!MyModel`. Checks `loader.context["MyModel"]`.
- **Import:** `!my.module.Class`. Attempts dynamic import.
- **Pydantic Integration:** Dracon constructs a dict/list from the YAML node, then passes it to `Model.model_validate()`.

## 9. Deferred Execution

Mechanisms for values unavailable at load time (runtime secrets, Python loop objects). Before reaching for `!deferred`, check if lazy `!define` (section 3.1) solves your problem -- if all info is available at composition time, lazy `!define x: !Type { ... }` is simpler.

### 9.1. `!deferred` / `DeferredNode`

Pauses the construction of an entire branch. Composition directives inside (`!each`, `!if`, `!fn`, `<<:`, `!include`) are preserved as-is and only evaluated at runtime.

- **YAML:** `output: !deferred "/tmp/${run_id}"`
- **Result:** `DeferredNode` object holding the raw pre-composition subtree and context.
- **One-step:** `node.copy().construct(context={'run_id': 123})` -- compose + construct in one call.
- **Two-step:** `composed = compose(node, context={...})` then `result = construct(composed)` -- inspect or modify the composed tree between phases.
- **Options:** `!deferred::clear_ctx=True` optimizes memory by dropping load-time context.

### 9.2. `Resolvable[T]`

Wrapper type for Pydantic models.

- **Definition:** `field: Resolvable[int]`
- **Usage:** `obj.field.resolve(context={...})`.

## 10. CLI Generation (`dracon.commandline`)

Dracon auto-generates CLIs from Pydantic models. The recommended approach is the `@dracon_program` decorator.

### 10.1. The `@dracon_program` Decorator (Recommended)

Turn any Pydantic model into a CLI program with a single decorator:

```python
from dracon import dracon_program, Arg, DeferredNode
from pydantic import BaseModel
from typing import Annotated, List

@dracon_program(
    name="my-app",
    description="My application",
    context_types=[DatabaseConfig],  # Types available for !Tags
    deferred_paths=["/secrets/**"],  # Paths to keep as DeferredNode
)
class AppConfig(BaseModel):
    env: Annotated[str, Arg(short='e', help="Environment")]
    db: DatabaseConfig
    workers: int = 4

    def run(self):
        """Optional: called by .invoke() after config is loaded."""
        print(f"Running in {self.env} with {self.workers} workers")
        return self.workers

# Usage patterns:
AppConfig.cli()                              # Run as CLI (parses sys.argv)
result = AppConfig.invoke("+config.yaml")    # Load config, call run(), return result
instance = AppConfig.from_config("cfg.yaml") # Load config, return instance
config = AppConfig.load("config.yaml")       # Load as dict (before validation)
```

### 10.2. Decorator Options

| Option | Description |
|--------|-------------|
| `name` | CLI program name |
| `description` | Help text description |
| `context` | Dict of context variables for `${...}` |
| `context_types` | List of types to add to context |
| `deferred_paths` | Paths to keep as `DeferredNode` |
| `auto_context` | Capture types from caller's namespace |
| `config_files` | List of `ConfigFile(...)` for auto-discovery |
| `sections` | List of `HelpSection(title, body)` for extra help content |
| `epilog` | Footer text for help output |

### 10.3. Alternative: `make_program`

For more control, use `make_program` directly:

```python
from dracon import make_program, Arg

program = make_program(Config, name="my-app")
config, raw_args = program.parse_args()
```

### 10.4. Argument Precedence (Last Wins)

1.  **Model Defaults:** Defined in Pydantic.
2.  **Config Files (`+path`):** Positional args starting with `+`. Loaded/merged sequentially.
3.  **Context Vars (`++`):** Arguments starting with `++` (`++k=v`) define context variables.
4.  **CLI Flags:** Direct overrides (`--env prod`, `--db.host localhost`).

### 10.5. Auto-Discovered Config Files

Declare config files that are automatically loaded as the base layer (below `+file.yaml` and `--flag` overrides):

```python
@dracon_program(
    config_files=[
        ConfigFile("~/.myapp/config.yaml"),                    # home-dir defaults
        ConfigFile(".myapp.yaml", search_parents=True),        # cascade: walk up from CWD, merge all matches
        ConfigFile("required.yaml", required=True),            # error if missing
        ConfigFile("db.yaml", selector="database.primary"),    # extract sub-key
    ],
)
class AppConfig(BaseModel): ...
```

### 10.6. Advanced CLI Syntax

- **Explicit File Load:** `--field +config.yaml`.
- **Reference Load:** `--field +config.yaml@sub.key`.
- **Collections:** `--tags a b c` (List), `--opts k=v a.b=c` (Dict).
- **Trace:** `--trace-all` enables composition tracing (also via `DRACON_TRACE=1`).

## 11. Callable Configs (`make_callable`)

Turn a YAML config into a reusable callable function:

```python
from dracon import make_callable

# Create a callable from a config file
create_model = make_callable(
    "model_config.yaml",
    context_types=[ModelConfig, OptimizerConfig],
)

# Call with runtime parameters
model1 = create_model(learning_rate=0.01, layers=3)
model2 = create_model(learning_rate=0.001, layers=5)
```

### 11.1. Options

| Option | Description |
|--------|-------------|
| `context` | Dict of context variables |
| `context_types` | List of types to add to context |
| `auto_context` | Capture types from caller's namespace |

### 11.2. From DeferredNode

You can also create a callable from an existing `DeferredNode`:

```python
cfg = load("config.yaml", deferred_paths=["/model"])
create_model = make_callable(cfg["model"])
model = create_model(name="custom")
```

## 12. Composition Tracing

Dracon tracks the provenance of every config value through composition. Tracing is **enabled by default** (`DraconLoader(trace=True)`).

### 12.1. Accessing Traces

```python
# Via CompositionResult
comp = loader.compose("config.yaml")
comp.trace.format_path("db.port")       # single path history
comp.trace.format_all()                  # full provenance tree
comp.trace.format_path_rich("db.port")   # rich-formatted Panel
comp.trace.format_all_rich()             # rich-formatted Table

# Trace entries
entries = comp.trace.get("db.port")      # list[TraceEntry]
all_entries = comp.trace.all()           # dict[str, list[TraceEntry]]
```

### 12.2. ViaKind (Provenance Types)

Each `TraceEntry` records a `via` field indicating how the value arrived:

| ViaKind | Meaning |
|---------|---------|
| `definition` | Local key definition in the YAML tree |
| `file_layer` | Loaded from a config file layer |
| `include` | Included from another source |
| `merge` | Merged from another value |
| `if_branch` | Selected by an `!if` branch |
| `each_expansion` | Created by an `!each` loop |
| `cli_override` | Set via CLI argument |
| `set_default` | Set by `!set_default` |
| `define` | Set by `!define` |
| `context_variable` | From a context variable |

### 12.3. TraceEntry Structure

```python
@dataclass
class TraceEntry:
    value: Any                          # the value at this step
    source: Optional[SourceContext]     # file/line/column
    via: ViaKind                        # how it got here
    detail: str                         # human-readable context
    replaced: Optional[TraceEntry]      # previous value (auto-linked)
```

## 13. Debugging & Tooling

### 13.0. `dracon` CLI

Unified command with subcommands `show` and `completions`.

- **`dracon show <file|program> [OPTIONS]`**: Inspect configs in raw YAML mode (files) or program-aware mode (installed `@dracon_program` names). Supports `-c` (construct), `-r` (resolve), `-j` (json), `-s` (select), `--full` (exhaustive nested defaults), `--schema` (JSON Schema), `--trace`/`--trace-all` (provenance), `--show-vars`.
- **`dracon completions install`**: Install shell completions. Writes cached script to `~/.dracon/completions.{shell}`, background regen hourly. Completions are <50ms (source regex, no Python imports for common cases). Programs with `__dracon_complete__(prefix, tokens)` get dynamic completions (e.g. job names from daemon).
- **`compose(deferred_node, context={})`**: Compose a `DeferredNode` with runtime context, returning a `CompositionResult` for inspection before construction.
- **`construct(node_or_comp, context={})`**: Construct a `DeferredNode` or `CompositionResult` into Python objects.
- **`resolve_all_lazy(obj)`**: Recursively force evaluation of all `LazyInterpolable` values.
- **`--trace-all`** (CLI flag): Enable composition tracing for `@dracon_program` apps.
- **Env Vars:**
  - `DRACON_TRACE=1`: Enable composition tracing (also enabled by default in DraconLoader).
  - `ENABLE_FTRACE=1`: Enable function-level execution tracing (colored entry/exit/args).
  - `ENABLE_SER_DEBUG=1`: Enable pickle/serialization debug output.

### 13.1. Error Diagnostics

Dracon provides rich, structured error messages with source context:

- `DraconError`: Base error with file/line/column context and trace history.
- `CompositionError`: Errors during the composition phase.
- `EvaluationError`: Expression evaluation failures in `${...}`.
- `UndefinedNameError`: Undefined variable in expression context.
- `SchemaError`: Pydantic validation failures.

All errors carry `SourceContext` (file, line, column, keypath, include trace chain) and auto-attach composition trace history when available.

---

## 14. Real-World Architecture Example: "The Dynamic Skeleton"

_Based on `biocompiler/biocomp-jobs/train`._

This pattern separates the **topology** of the experiment (what files are involved) from the **hyperparameters** (what values are used) and the **runtime execution** (loggers, deferred jobs). It relies heavily on **dynamic includes** and **context injection**.

### 14.1. The Components

1.  **The Skeleton (`start.yaml`)**: The entry point. It defines _logic_, not just data. It declares variables (`!set_default`) that the CLI is expected to fill, acting as an interface contract.
2.  **The Payload (`training_sets/`)**: A library of composable configurations. Files here are often Unions or Differences of other files.
3.  **The Logic (`training_configs/`)**: Hyperparameter presets (e.g., `regression-nolayerinfo.yaml`).
4.  **The Python Bridge (`run_training.py`)**: The runtime environment that injects live objects (like `best_model`) into deferred nodes.

### 14.2. `start.yaml`: The Hub

The skeleton uses interpolation _inside_ include paths. This allows the CLI to swap entire dataset definitions by changing a single string variable.

```yaml
# 1. Define Interface (CLI Targets)
!set_default training_set_file: "composite_sets/default.yaml"
!set_default base_config: "regression"
!set_default runname: "default_run"

# 2. Dynamic Logic
# Construct a path dynamically based on CLI input.
# Dracon resolves ${training_set_file}, then executes the include.
training_set: !CleanupFilter
  source_set: !include file:${training_set_file}

# 3. Layered Configuration
# Load the base config (e.g. regression hyperparameters).
# Strategy {+>} ensures start.yaml defaults (if any) take precedence, but usually
# this merges the specific config parameters onto the skeleton.
<<{+>}[~>]: !include file:$DIR/training_configs/${base_config}.yaml

# 4. Deferred Runtime Jobs
loggers:
  # Plots need access to python variables 'step' and 'model' which don't exist yet.
  # They will be constructed inside the training loop.
  - <<: !include file:$DIR/loggers/plot_inner_nodes
```

### 14.3. Execution Example

The CLI command injects the "flesh" onto the "skeleton".

```bash
biocomp-train \
  +biocomp-jobs/train/start.yaml \
  ++training_set_file biocomp-jobs/train/basic_sets/1_Pgu_extra.yaml \
  ++base_config "regression-nolayerinfo" \
  ++runname "1_Pgu_extra"
```

**What happens internally:**

1.  **Load `start.yaml`**: Dracon sees the `+`.
2.  **Context Injection**: `++training_set_file`, `++base_config`, etc., are added to the global context.
3.  **Composition**:
    - `!include file:${training_set_file}` evaluates to `!include file:.../1_Pgu_extra.yaml`. The specific dataset is loaded.
    - `!include file:.../${base_config}.yaml` evaluates and loads the regression config.
    - `<<{+>}` merges the regression config into the root.
4.  **Construction**: The `TrainingProgram` model (from `run_training.py`) validates the final structure.
5.  **Runtime**: The Python script loops. At specific steps, it calls `construct(logger_node, context={'model': current_model})`, activating the deferred plotters defined in `start.yaml`.

### 14.4. Why this pattern?

- **Combinatorial Power**: You can test $M$ datasets against $N$ hyperparameter sets with $M+N$ config files (plus one skeleton), rather than $M \times N$ files.
- **Context Awareness**: Configs know where they live (`$DIR`). You can move the entire folder structure, and relative includes inside `basic_sets/*.yaml` still work.
- **Runtime Injection**: The config defines _what_ to plot, but the Python code provides the _data_ to plot, bridging the gap between static config and dynamic runtime state without hardcoding logic in Python.
