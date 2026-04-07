# The Three Phases

Everything in Dracon flows through three phases: **compose**, **construct**, **resolve**. If you understand these, the rest of the system follows naturally.

```
Parse YAML
  |
  v
Compose (node tree manipulation)
  |
  v
[CompositionResult]  <-- you can inspect/modify here
  |
  v
Construct (Python objects)
  |
  v
[models, dicts, lists]
  |
  v
Resolve (lazy expressions on access)
  |
  v
[final values]
```

---

## Phase 1: Composition

Raw YAML text is parsed into a node tree, then Dracon walks that tree and transforms it. The output is a `CompositionResult`: a clean node tree ready for construction.

No Python objects exist yet. No Pydantic models, no custom classes. Just YAML nodes with tags, values, and context dictionaries attached.

What runs during composition:

| Instruction | What it does |
|---|---|
| `!include` | Pull in external YAML content |
| `<<:` | Merge nodes together |
| `!define` | Bind a name to a value in scope |
| `!set_default` | Bind a name, but softly (overridable) |
| `!require` | Declare that a variable must be provided |
| `!if` | Conditional node inclusion |
| `!each` | Iterate and generate nodes |
| `!fn` | Create callable templates |
| `!pipe` | Chain callables |
| `!assert` | Enforce contracts (runs after other instructions) |

The order matters. Instructions are processed top-down by depth in the tree, shallowest first. Includes are resolved after instructions, and merges after includes. This means `!define` values are available to `!if` conditions in the same mapping, but only for nodes that appear after the define.

### What you can do between phases

The `CompositionResult` is a real object you can hold onto. You can:

- Inspect it with `dracon show` on the CLI
- Modify the node tree programmatically
- Serialize it
- Pass it to `construct()` later, possibly with different contexts

```python
from dracon import DraconLoader

loader = DraconLoader()
comp = loader.compose("config.yaml")
# comp.root is the node tree
# comp.defined_vars has all !define'd variables
# comp.trace has the full provenance trail
```

---

## Phase 2: Construction

The composed node tree is walked top-down and turned into Python objects.

- Type tags like `!MyModel` or `!my.module.MyClass` are resolved to Python classes
- Pydantic models are validated via `model_validate()`
- `!noconstruct` nodes are left as raw dicts/lists
- `!deferred` nodes are wrapped in `DeferredNode` and paused
- `${...}` expressions in non-lazy containers are resolved here

The constructor looks at each node's tag to decide what to do. A tag like `!MyModel` triggers a lookup: first in the loader's context (for types defined via `!define`), then via Python import resolution. If the tag resolves to a Pydantic model, the node's children become the model's field values.

```yaml
!MyModel
name: Alice
age: 30
```

This constructs `MyModel(name="Alice", age=30)`, with Pydantic handling validation and coercion.

### What about `${...}` expressions?

It depends on the container. If the constructed object is a regular dict or Pydantic model (not a `Dracontainer`), expressions are resolved eagerly during construction. If the container is a `Dracontainer` (Dracon's lazy dict/list types), expressions become `LazyInterpolable` objects that resolve on first access. See Phase 3.

---

## Phase 3: Resolution

After construction, some values are still deferred:

- **`LazyInterpolable`**: expressions inside `Dracontainer` objects. They resolve when you access the attribute or key. The first access evaluates the expression, and the result replaces the lazy wrapper in-place.
- **`DeferredNode`**: entire subtrees that were paused with `!deferred`. They wait for an explicit `.construct(context={...})` call, which runs the full compose-then-construct pipeline with the provided runtime context.

This is where runtime values enter the picture. A `DeferredNode` can be constructed multiple times with different contexts, producing different results each time.

```python
# deferred node waiting for runtime context
result = node.construct(context={"env": "production", "region": "us-east-1"})
```

Lazy resolution also means that circular references between fields are fine, as long as they don't form an infinite loop at evaluation time.

---

## Why this separation matters

The three-phase design is not accidental. Each boundary gives you something:

**Composition is data transformation with controlled I/O.** No Python imports happen, no arbitrary code execution (beyond `${...}` evaluation for `!define` values). The only I/O is include resolution: `!include file:`, `env:`, `pkg:`, and `cascade:` read from the filesystem or environment. But the output is still a deterministic node tree that you can inspect before constructing anything.

**You can inspect between phases.** The `CompositionResult` is a snapshot of the fully-merged, instruction-processed config tree. The `dracon show` CLI command uses this to display configs without constructing them. You can also use the composition trace to see exactly where each value came from.

**Construction can be deferred.** A `DeferredNode` captures the node tree and a loader, so you can construct it later with different contexts. This enables patterns like:

- Hot-reload: re-construct from the same tree when the config file changes
- Multi-environment: construct the same tree with `env=staging` or `env=production`
- Testing: construct with mock values injected into context

**The same YAML can be constructed multiple times.** Because composition produces an immutable-ish node tree and construction creates new objects each time, there's no shared mutable state between constructions.

---

## The full pipeline in detail

Here is what `DraconLoader.load("config.yaml")` actually does, step by step:

1. **Parse** -- `ruamel.yaml` reads the YAML text into raw nodes
2. **Compose** -- `DraconComposer` upgrades nodes to Dracon types (`DraconMappingNode`, `InterpolableNode`, etc.) and detects special nodes (includes, merges, interpolables)
3. **Preprocess references** -- `@path` and `&path` references are resolved to node pointers
4. **Process deferred** -- nodes at `deferred_paths` are wrapped in `DeferredNode`
5. **Propagate context** -- the loader's context dict is merged into every node's context
6. **Process instructions** -- `!define`, `!set_default`, `!if`, `!each`, `!fn`, etc. are executed top-down
7. **Process includes** -- `!include` nodes are replaced with their loaded content
8. **Check requirements** -- `!require` variables that are still missing cause an error
9. **Process assertions** -- `!assert` conditions are evaluated
10. **Process merges** -- `<<:` merge keys are resolved
11. **Save references** -- `@path` reference targets are snapshot for construction
12. **Construct** -- the cleaned node tree is walked and turned into Python objects

Steps 2-11 are composition (Phase 1). Step 12 is construction (Phase 2). Resolution (Phase 3) happens lazily after construction returns.

If you're loading multiple files, a `CompositionStack` handles the layering: each file is composed independently, then the results are merged in order. See [Context and Scope](context-and-scope.md) for how variables flow between layers.
