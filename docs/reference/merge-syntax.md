# Merge Syntax

Full grammar for Dracon merge keys.

---

## Syntax

```
<<{DICT_OPTS}[LIST_OPTS](<CTX>)@TARGET: source
```

All parts except `<<` and the source value are optional. Any omitted section uses its default.

### Dict options `{...}`

Controls how mapping (dict) values are merged.

| Symbol | Meaning |
|--------|---------|
| `+` | **Append mode**: recursively merge sub-dicts, append new keys |
| `~` | **Replace mode**: fully replace conflicting keys, append new keys |
| `<` | **New wins**: when keys conflict, the new (source) value takes priority |
| `>` | **Existing wins**: when keys conflict, the existing (target) value stays |
| `N` | **Depth limit**: stop recursive merging after N levels (e.g. `{+>2}`) |

### List options `[...]`

Controls how sequence (list) values are merged.

| Symbol | Meaning |
|--------|---------|
| `+` | **Append mode**: concatenate lists |
| `~` | **Replace mode**: replace the entire list |
| `<` | **New wins**: use the new list (or put new items first when appending) |
| `>` | **Existing wins**: use the existing list (or put existing items first when appending) |
| `N` | **Depth limit**: stop after N levels |

### Context propagation `(...)`

| Symbol | Meaning |
|--------|---------|
| `<` | Propagate new context upward to sibling nodes |

Only `(<)` is supported. Without it, context from the merge source stays local.

### Target `@keypath`

Merge the source into a specific subtree of the target:

```yaml
<<@database: !include file:db-overrides.yaml
```

When `@keypath` is present, the default priority flips to **new wins** (`<`).

---

## Defaults

The bare `<<:` key is equivalent to `<<{>+}[>~]:` -- recursive append for dicts (existing wins), replace for lists (existing wins).

---

## Quick Reference

| Merge Key | Dict Behavior | List Behavior |
|-----------|---------------|---------------|
| `<<:` | Recursive merge, existing wins | Replace, existing wins |
| `<<{<+}[<~]:` | Recursive merge, new wins | Replace, new wins |
| `<<{>~}[>~]:` | Replace, existing wins | Replace, existing wins |
| `<<{<~}:` | Replace, new wins | (default) Replace, existing wins |
| `<<{+<}[+<]:` | Recursive merge, new wins | Append, new wins |
| `<<{>+2}:` | Recursive merge, max depth 2, existing wins | (default) |
| `<<(<):` | (default) + propagate context | (default) |
| `<<@db.settings:` | Target `db.settings`, new wins (default for @) | New wins |
| `<<{>+}@db:` | Target `db`, recursive merge, existing wins | (default) |

---

## Duplicate Merge Keys

YAML does not allow duplicate keys. When you need multiple merge operations in the same mapping, Dracon disambiguates with a trailing suffix that gets stripped during processing:

```yaml
base:
  <<: !include file:defaults.yaml
  <<_overrides: !include file:overrides.yaml
```

Any suffix after `<<` that starts with `_` (and is not part of the merge key grammar) serves as a disambiguation label and is ignored.

---

## Soft vs Hard Keys

Merge respects `!set_default` (soft) vs `!define` (hard) priority. When merging:

- A hard value always beats a soft value, regardless of the merge priority setting
- A soft value only wins over another soft value if it has merge priority

This means `!set_default` values act as true defaults that any explicit definition can override, even with an existing-wins merge strategy.
