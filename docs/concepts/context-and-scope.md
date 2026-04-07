# Context and Scope

Context is the dictionary of names available for `${...}` evaluation and tag resolution at any given node in the tree. Understanding how context flows through the system is key to predicting what Dracon will do with your config.

---

## What "context" is, concretely

Every node in the YAML tree can have a `.context` dictionary attached to it. When Dracon evaluates `${some_expression}`, it looks up names in the current node's context. When it encounters a type tag like `!MyModel`, it also checks the context for type definitions.

Context is not global. Different nodes can have different contexts. A `!define` at the top of a file adds to the context of that node's descendants, but not its ancestors or unrelated siblings.

---

## Context sources

From lowest to highest precedence:

### 1. Built-in functions

Always available. These include:

| Name | What it is |
|---|---|
| `getenv` | `os.getenv` |
| `getcwd` | `os.getcwd` |
| `listdir` | `os.listdir` |
| `join` | `os.path.join` |
| `basename` | `os.path.basename` |
| `dirname` | `os.path.dirname` |
| `expanduser` | `os.path.expanduser` |
| `isfile` | `os.path.isfile` |
| `isdir` | `os.path.isdir` |
| `Path` | `pathlib.Path` |
| `now` | Returns current datetime as string (format arg optional) |

### 2. Loader context

Passed programmatically when creating a `DraconLoader` or via `@dracon_program`:

```python
loader = DraconLoader(context={"project": "myapp", "version": 3})
```

These are available everywhere in the config tree.

### 3. File context

Set automatically per-file by the `file:` loader when processing `!include`:

| Variable | Value |
|---|---|
| `DIR` | Directory containing the file |
| `FILE` | Full file path |
| `FILE_STEM` | Filename without extension |
| `FILE_PATH` | Same as `FILE` |

These are scoped to the included file and its descendants.

### 4. `!set_default` variables (soft)

```yaml
!set_default batch_size: 32
```

Creates a soft binding. Soft values can be overridden by hard values (`!define`) from anywhere in the merge stack, even from a parent that includes this file. This is the mechanism behind template parameters.

### 5. `!define` variables (hard)

```yaml
!define batch_size: 64
```

Creates a hard binding. Hard values override soft values during merging, regardless of merge priority settings.

### 6. CLI overrides

```bash
my_program ++batch_size=128
my_program --define.batch_size=128
```

CLI-injected values are treated as hard defines. They override everything except other hard defines that come later in the merge stack.

---

## Hard vs soft: the priority system

This is one of the more subtle parts of Dracon, and it matters a lot for template-based configs.

Every context variable is either **hard** or **soft**:

- `!define` creates hard values
- `!set_default` (also spelled `!define?`) creates soft values
- Loader context values are hard
- CLI overrides are hard

When two contexts are merged (e.g., during `!include` processing or layer stacking), hard values always beat soft values, regardless of the `>` or `<` in the merge key. The merge key's priority only decides ties between two hard values or two soft values.

This is what makes the template pattern work:

```yaml
# template.yaml
!set_default optimizer: adam       # soft
!set_default lr: 0.001             # soft
training:
  optimizer: ${optimizer}
  learning_rate: ${lr}
```

```yaml
# experiment.yaml
!define lr: 0.01                   # hard, overrides the soft default

<<: !include file:template.yaml
```

Result: `optimizer` stays `adam` (soft default, not overridden), `lr` becomes `0.01` (hard beats soft).

---

## Scope rules

**A `!define` is visible to the current node and all its descendants.** It propagates downward through the tree.

**It is NOT visible to siblings defined before it.** Nodes are processed top-down, so a `!define` only affects nodes that come after it in the YAML source.

```yaml
before: ${x}    # ERROR: x is not defined yet

!define x: 42

after: ${x}     # OK: 42
```

**`!fn` calls get isolated scope.** When you call a `DraconCallable`, the template is deep-copied and composed with a fresh loader. The caller's context is not leaked into the template, and the template's internal `!define` values do not leak back to the caller. Arguments are passed explicitly as kwargs.

```yaml
!define helper: !fn
  !require name
  !define internal_var: something   # not visible outside
  result: ${name}

output: ${helper(name="test")}
# internal_var is NOT available here
```

---

## Context propagation through includes

By default, includes are **isolated**. The included file composes with its own context. Its `!define` values stay inside.

```yaml
# vocab.yaml
!define MyType: !fn
  kind: special

# config.yaml
<<: !include file:vocab.yaml
item: !MyType    # ERROR: MyType not in scope
```

To make the included file's definitions available in the parent, use context propagation `(<)` on the merge key:

```yaml
# config.yaml
<<(<): !include file:vocab.yaml
item: !MyType    # OK: MyType propagated up
```

This is one-way. The parent's context does not flow into the include (the include's context comes from its own content plus the loader context). Only the include's exports flow up to the parent.

See [The Merge Operator](merge-algebra.md) for more on `(<)`.

---

## CompositionStack scopes

When loading multiple config files as layers (via `DraconLoader.load([file1, file2, ...])` or programmatically via `CompositionStack`), each layer can have a scope that controls how context flows between layers:

### `ISOLATED` (default)

Each layer composes independently. No context flows between layers. The layers are merged purely by node-level merge semantics.

```python
from dracon.stack import CompositionStack, LayerSpec, LayerScope

stack = CompositionStack(loader, [
    LayerSpec(source="base.yaml"),
    LayerSpec(source="overrides.yaml"),  # cannot see base.yaml's !define values
])
```

### `EXPORTS`

`!define` and `!set_default` variables from earlier layers are available to later layers. This lets you define shared constants in a base layer and reference them in overlay layers.

```python
stack = CompositionStack(loader, [
    LayerSpec(source="constants.yaml"),
    LayerSpec(source="config.yaml", scope=LayerScope.EXPORTS),
    # config.yaml can use ${...} references to constants.yaml's !define'd values
])
```

Soft/hard priority is preserved across layers: a `!set_default` in the base layer is still soft when seen by later layers, so a `!define` in a later layer can override it.

### `EXPORTS_AND_PREV`

Like `EXPORTS`, but also injects a `PREV` variable containing a snapshot of the accumulated merge result so far (as a constructed Python object). This lets later layers reference the actual merged values from earlier layers, not just their `!define` variables.

```python
stack = CompositionStack(loader, [
    LayerSpec(source="base.yaml"),
    LayerSpec(source="derived.yaml", scope=LayerScope.EXPORTS_AND_PREV),
    # derived.yaml can use ${PREV.some_key} to reference base.yaml's merged values
])
```

---

## Summary

The precedence stack, from weakest to strongest:

1. Built-in functions
2. Loader context
3. File context (`DIR`, `FILE`, etc.)
4. `!set_default` (soft)
5. `!define` (hard)
6. CLI `++var=value` (hard)

Scope flows downward through the tree. Context propagation with `(<)` flows upward through includes. Layer scopes control horizontal flow between files in a merge stack.

When in doubt, `dracon show` will display the fully-composed config with all variables resolved, so you can see exactly what ended up where.
