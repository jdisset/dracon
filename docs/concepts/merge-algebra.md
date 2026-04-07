# The Merge Operator

The `<<:` merge key is how Dracon combines nodes. Standard YAML has a basic merge key (`<<: *anchor`), but Dracon extends it with mode, priority, depth, context propagation, and target path controls.

!!! note
    For the full syntax reference, see [Merge Syntax](../reference/merge-syntax.md).

---

## The full syntax

```
<<{DICT_OPTIONS}[LIST_OPTIONS](<CTX>)@TARGET_PATH: source
```

Everything in brackets is optional. The bare `<<:` works fine for simple cases.

---

## Dictionary options: `{MODE/PRIORITY/DEPTH}`

Two mode characters and an optional depth number, inside `{}`:

| Character | Meaning |
|---|---|
| `+` | Recurse into sub-dicts, append new keys |
| `~` | Replace conflicting keys wholesale |
| `>` | Existing values win on conflict |
| `<` | New (incoming) values win on conflict |

And optionally a number for depth limit (e.g., `{+2}` recurses at most 2 levels).

**Defaults:** `{>+}` -- recurse into sub-dicts, existing values win.

### What "existing" and "new" mean

The node that already sits in the tree is "existing". The node being merged in (the value of `<<:`) is "new". When both have the same key:

- `>` keeps the existing value
- `<` replaces it with the new value

```yaml
# existing values win (default)
base:
  x: 1
  y: 2
<<:
  x: 99   # ignored, x already exists
  z: 3    # added, new key
# result: {x: 1, y: 2, z: 3}
```

```yaml
# new values win
base:
  x: 1
  y: 2
<<{<+}:
  x: 99   # overwrites x
  z: 3    # added
# result: {x: 99, y: 2, z: 3}
```

### Recurse vs replace

With `+` (recurse/append), nested dicts are merged recursively:

```yaml
base:
  db:
    host: localhost
    port: 5432
<<{<+}:
  db:
    host: prod.example.com
# result: db: {host: prod.example.com, port: 5432}
```

With `~` (replace), the entire sub-dict is swapped:

```yaml
base:
  db:
    host: localhost
    port: 5432
<<{<~}:
  db:
    host: prod.example.com
# result: db: {host: prod.example.com}
#   port is gone -- the whole db dict was replaced
```

### Depth limit

`{+2}` means "recurse, but only 2 levels deep". At the depth limit, conflicting sub-dicts are treated as atoms (replaced or kept, depending on priority).

---

## List options: `[MODE/PRIORITY]`

Same characters, inside `[]`:

| Character | Meaning |
|---|---|
| `+` | Concatenate lists |
| `~` | Replace the whole list (default) |
| `>` | Existing list comes first when concatenating |
| `<` | New list comes first when concatenating |

**Defaults:** `[>~]` -- replace lists, existing wins.

```yaml
# concatenate, new items after existing
items: [a, b]
<<[>+]:
  items: [c, d]
# result: items: [a, b, c, d]

# concatenate, new items before existing
items: [a, b]
<<[<+]:
  items: [c, d]
# result: items: [c, d, a, b]
```

---

## Context propagation: `(<)`

The `(<)` option has two effects depending on what you are merging:

### With `!include`: propagate `!define`d vars upward

Normally, an include's `!define` variables stay inside the include. With `(<)`, they propagate up to the parent scope:

```yaml
# vocab.yaml
!define MyCustomModel: !fn
  !set_default layers: 4
  type: custom
  num_layers: ${layers}

---
# config.yaml
<<(<): !include file:vocab.yaml

model: !MyCustomModel
  layers: 8
```

Without `(<)`, `MyCustomModel` would not be visible in `config.yaml`. With it, the `!define` from the vocabulary file becomes available as a tag in the parent.

### With tag merges: enable `!define`d callables as YAML tags

This is the mechanism that makes vocabulary files work. When you define a callable via `!fn` and propagate it with `(<)`, it becomes available as a type tag (`!MyCallable`) in the parent scope.

---

## Target path: `@PATH`

Merge into a subtree instead of the current node:

```yaml
<<@database:
  host: prod.example.com
  pool_size: 20
```

This is equivalent to:

```yaml
database:
  <<:
    host: prod.example.com
    pool_size: 20
```

But without needing to nest the merge key inside the target. Useful when merging into a deeply nested path or when the target does not exist yet.

!!! note
    When `@PATH` is present, the default priority flips to "new wins" (`<`). This makes `<<@path:` behave like an override by default.

---

## Soft vs hard values

This interacts with the merge system in an important way.

- `!define` creates **hard** values
- `!set_default` creates **soft** values

During merging, soft values yield to hard values, regardless of the merge priority setting. This is how template defaults work:

```yaml
# template.yaml
!set_default batch_size: 32      # soft
!set_default learning_rate: 0.001  # soft

training:
  batch_size: ${batch_size}
  lr: ${learning_rate}
```

```yaml
# config.yaml
!define batch_size: 64  # hard -- overrides the soft default

<<: !include file:template.yaml
```

The result has `batch_size: 64` (hard wins) and `learning_rate: 0.001` (soft default, nothing to override it).

This is independent of `>` vs `<` in the merge key. Soft/hard priority is a separate layer on top of the merge strategy.

---

## Multiple merge keys

You can have multiple `<<:` keys in one mapping. They are processed in source order (top to bottom):

```yaml
<<: !include file:base.yaml
<<: !include file:overrides.yaml
```

YAML does not actually allow duplicate keys. Dracon handles this by accepting suffix-disambiguated keys:

```yaml
<<{>+}base: !include file:base.yaml
<<{<+}overrides: !include file:overrides.yaml
```

The suffix after the closing bracket/paren (here `base` and `overrides`) is ignored by the merge key parser; it just makes the keys unique for the YAML parser.

---

## Quick reference

| Pattern | Behavior |
|---|---|
| `<<: *ref` | Standard YAML anchor merge (existing wins, recurse dicts) |
| `<<{<+}:` | Override merge (new wins, recurse dicts) |
| `<<{<~}:` | Override merge (new wins, replace dicts wholesale) |
| `<<[+]:` | Concatenate lists (existing first) |
| `<<[<+]:` | Concatenate lists (new first) |
| `<<(<):` | Propagate context from source to parent |
| `<<@db:` | Merge into the `db` subtree (new wins by default) |
| `<<{<+}[<+](<):` | Full combo: override dicts, concat lists, propagate context |

---

## Tradeoffs

The merge system is the most complex part of Dracon. A few things to keep in mind:

- **Order matters.** Multiple merge keys are processed top to bottom, and later merges see the result of earlier ones.
- **Soft/hard priority is invisible in the YAML.** You cannot tell from looking at a value whether it is soft or hard. You need to know whether it was set by `!define` or `!set_default`.
- **Deep recursion can be surprising.** `{+}` recurses all the way down. If you only want to merge the top level, use `{+1}` or `{~}`.
- **Context propagation is one-way.** `(<)` only propagates from source to parent, not the other direction. The source does not see the parent's context.
