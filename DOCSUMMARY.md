# Dracon: The Engineer's Manual

**Dracon** is a configuration engine that strictly separates **Composition** (YAML graph manipulation) from **Construction** (Python object instantiation). It creates a programmable configuration layer before your application logic ever sees the data.

## 1. The Core Lifecycle

1.  **Composition:** Raw text is parsed. Instructions (`!if`, `!define`) modify the tree. Includes are resolved recursively. Merges (`<<:`) are applied.
2.  **Construction:** The final node tree is traversed. Python objects (Pydantic models, primitives) are instantiated.
3.  **Resolution:** Interpolations (`${...}`) are wrapped in `LazyInterpolable`. They evaluate **only upon access**.

## 2. Python API

### 2.1. Loading

```python
from dracon import load, loads, dump, DraconLoader

# 1. Simple Load
cfg = load(["base.yaml", "override.yaml"], context={"MyModel": MyModel})

# 2. Advanced Loader
loader = DraconLoader(
    context={"func": my_func},          # Available in ${...} and !Tags
    interpolation_engine='asteval',     # 'asteval' (safe) or 'eval' (unsafe)
    deferred_paths=['/secrets/**'],     # Force paths to be DeferredNodes
    enable_shorthand_vars=True          # Allow $VAR alongside ${VAR}
)
cfg = loader.load("config.yaml")

# 3. Composition Only (Inspect the graph before construction)
comp_result = loader.compose("config.yaml") # Returns CompositionResult
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

- **`!define key: value`**: Sets `key` in the context.
- **`!set_default key: value`**: Sets `key` only if it doesn't exist in the context (useful in included files).

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

### 3.4. Construction Control

- **`!noconstruct`**: The node is processed (anchors/defines are valid) but the node is removed before the Construction phase.
- **`__dracon__` Prefix**: Any key starting with `__dracon__` is treated as `!noconstruct`.

## 4. The Merge Operator (`<<:`)

Dracon extends the standard YAML merge key (`<<:`) to provide precise control over combination logic.

**Syntax:** `<<{DICT_OPTS}[LIST_OPTS]@TARGET_PATH: <source>`

### 4.1. Dictionary Strategy `{MODE/PRIORITY}`

- **Mode:**
  - `+` (**Append/Recurse**): Default. Merges keys. If values are dicts, recurses.
  - `~` (**Replace**): If key exists, overwrites value entirely (no recursion).
- **Priority:**
  - `>` (**Existing Wins**): Default. Current node keeps its value on conflict.
  - `<` (**New Wins**): Source node overwrites current node on conflict.
- **Depth:** e.g., `{+2}` limits recursion to 2 levels.

### 4.2. List Strategy `[MODE/PRIORITY]`

- **Mode:** `~` (**Replace**, Default) or `+` (**Concatenate**).
- **Priority:** `>` (**Existing First**, Default) or `<` (**New First**).

### 4.3. Examples

| Syntax     | Semantics  | Use Case                                                     |
| :--------- | :--------- | :----------------------------------------------------------- |
| `<<: *ref` | `{+>}[~>]` | Standard YAML. Recurse dicts (keep existing), Replace lists. |
| `<<{<+}:`  | `{<+}[~>]` | **Override**. Recurse dicts, new values overwrite old.       |
| `<<[+]:`   | `{+>}[+>]` | **Append**. Add items to end of lists.                       |
| `<<[+<]:`  | `{+>}[+<]` | **Prepend**. Add items to start of lists.                    |
| `<<@db:`   | `{<+}`     | Merge source into the `db` sub-key.                          |

## 5. Includes & Loaders

Inject external content at the current node.
**Syntax:** `!include <scheme>:<path>@<selector>`

### 5.1. Schemes

- **`file:`** (Default): Filesystem. Context adds `$DIR`, `$FILE`, `$FILE_STEM`.
- **`pkg:`**: Python resources (`pkg:package_name:path/inside/package.yaml`).
- **`env:`**: Environment variable string.
- **`var:`**: Dracon context variable (in-memory node).
- **Custom:** Register via `custom_loaders` in `DraconLoader`.

### 5.2. Selectors (`@`)

Select a specific subtree from the target. Uses KeyPath syntax.

- `!include file:conf.yaml@database.connections.0`

## 6. Interpolation & References

Expressions are strings enclosed in `${...}` (Runtime/Lazy) or `$(...)` (Parse-time/Immediate).

### 6.1. Reference Operators

- **`@path` (Value Reference)**: Retrieves the **final constructed value** at the given KeyPath.
  - Example: `url: "http://${@/server.host}"`.
- **`&path` (Node Copy)**: Retrieves the **raw YAML node** at composition time. Performs a **deep copy**.
  - Example: `new_obj: ${&/templates.base_obj}`.

### 6.2. KeyPath Syntax

Used in `@` references, `@` merges, include selectors, and API calls.

- Separator: `.`. Root: `/`. Escape: `\.`. Wildcards: `*` (matching only).

## 7. Tags & Type Resolution

- **Context:** `!MyModel`. Checks `loader.context["MyModel"]`.
- **Import:** `!my.module.Class`. Attempts dynamic import.
- **Pydantic Integration:** Dracon constructs a dict/list from the YAML node, then passes it to `Model.model_validate()`.

## 8. Deferred Execution

Mechanisms for values unavailable at load time (runtime secrets, Python loop objects).

### 8.1. `!deferred` / `DeferredNode`

Pauses the construction of an entire branch.

- **YAML:** `output: !deferred "/tmp/${run_id}"`
- **Result:** `DeferredNode` object holding the raw node and context.
- **Usage:** Manually call `dracon.construct(node, context={'run_id': 123})`.
- **Options:** `!deferred::clear_ctx=True` optimizes memory by dropping load-time context.

### 8.2. `Resolvable[T]`

Wrapper type for Pydantic models.

- **Definition:** `field: Resolvable[int]`
- **Usage:** `obj.field.resolve(context={...})`.

## 9. CLI Generation (`dracon.commandline`)

Dracon auto-generates a CLI from a Pydantic model.

```python
from dracon import make_program, Arg
class Config(BaseModel):
    env: Annotated[str, Arg(short='e', help="Env")]
    db: DatabaseConfig # Nested model
    secrets: Annotated[dict, Arg(is_file=True)] # Auto-load file content

program = make_program(Config)
config, raw_args = program.parse_args()
```

### 9.1. Argument Precedence (Last Wins)

1.  **Model Defaults:** Defined in Pydantic.
2.  **Config Files (`+path`):** Positional args starting with `+`. Loaded/merged sequentially.
3.  **Context Vars (`++`):** Arguments starting with `++` (`++k=v`) define context variables.
4.  **CLI Flags:** Direct overrides (`--env prod`, `--db.host localhost`).

### 9.2. Advanced CLI Syntax

- **Explicit File Load:** `--field +config.yaml`.
- **Reference Load:** `--field +config.yaml@sub.key`.
- **Collections:** `--tags a b c` (List), `--opts k=v a.b=c` (Dict).

## 10. Debugging & Tooling

- **`dracon-print <file>`**: Load and print composed configuration tree.
- **`resolve_all_lazy(obj)`**: Recursively force evaluation.
- **Env Vars:** `ENABLE_FTRACE=1` (trace), `ENABLE_SER_DEBUG=1` (pickle debug).

---

## 11. Real-World Architecture Example: "The Dynamic Skeleton"

_Based on `biocompiler/biocomp-jobs/train`._

This pattern separates the **topology** of the experiment (what files are involved) from the **hyperparameters** (what values are used) and the **runtime execution** (loggers, deferred jobs). It relies heavily on **dynamic includes** and **context injection**.

### 11.1. The Components

1.  **The Skeleton (`start.yaml`)**: The entry point. It defines _logic_, not just data. It declares variables (`!set_default`) that the CLI is expected to fill, acting as an interface contract.
2.  **The Payload (`training_sets/`)**: A library of composable configurations. Files here are often Unions or Differences of other files.
3.  **The Logic (`training_configs/`)**: Hyperparameter presets (e.g., `regression-nolayerinfo.yaml`).
4.  **The Python Bridge (`run_training.py`)**: The runtime environment that injects live objects (like `best_model`) into deferred nodes.

### 11.2. `start.yaml`: The Hub

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

### 11.3. Execution Example

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

### 11.4. Why this pattern?

- **Combinatorial Power**: You can test $M$ datasets against $N$ hyperparameter sets with $M+N$ config files (plus one skeleton), rather than $M \times N$ files.
- **Context Awareness**: Configs know where they live (`$DIR`). You can move the entire folder structure, and relative includes inside `basic_sets/*.yaml` still work.
- **Runtime Injection**: The config defines _what_ to plot, but the Python code provides the _data_ to plot, bridging the gap between static config and dynamic runtime state without hardcoding logic in Python.
