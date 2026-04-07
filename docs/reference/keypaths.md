# KeyPaths

Dot-separated paths for addressing nodes in a YAML tree.

```python
from dracon import KeyPath
```

---

## Syntax

| Element | Syntax | Meaning |
|---------|--------|---------|
| Separator | `.` | Descend one level |
| Root | `/` | Absolute path from the document root |
| Parent | `..` | Go up one level (two dots) |
| Current | `.` | Relative (single dot at start of a segment) |
| Escape dot | `\.` | Literal dot in a key name |
| Escape slash | `\/` | Literal slash in a key name |
| Single wildcard | `*` | Match any one segment |
| Multi wildcard | `**` | Match any number of segments (zero or more) |

---

## Examples

| Path | Meaning |
|------|---------|
| `/` | Document root |
| `/db.host` | Absolute path to `db` -> `host` |
| `db.host` | Relative path: `db` -> `host` |
| `..sibling` | Go up one level, then into `sibling` |
| `/servers.*.port` | `port` inside every item under `servers` |
| `/**.name` | All `name` keys at any depth |
| `my\.dotted\.key` | Single key named `my.dotted.key` |

---

## Path Simplification

Paths are simplified automatically. `a.b..c` becomes `a.c` (go into `b`, then back up, then into `c`). `/a/b` becomes `/b` (root resets).

---

## Usage Across Dracon

KeyPaths appear in several places:

| Context | Example |
|---------|---------|
| `@` value references | `${@db.port}` |
| Merge `@target` | `<<@database.settings: ...` |
| `deferred_paths` | `DraconLoader(deferred_paths=["/model", "data.*"])` |
| Include selectors | `!include file:config.yaml@database.host` |
| `CompositionStack` | Layer scope, context targeting |
| `-s` / `--select` flag | `dracon show config.yaml -s db.host` |
| `--trace` flag | `dracon show config.yaml --trace db.port` |

---

## API

### Construction

```python
kp = KeyPath("/db.host")       # from string
kp = KeyPath(["db", "host"])   # from parts list
```

### Navigation

| Method | Description |
|--------|-------------|
| `kp.parent` | New KeyPath one level up |
| `kp.down("child")` | Descend into child (mutates) |
| `kp + "child"` | Descend into child (new copy) |
| `kp.up()` | Go up one level (mutates) |
| `kp.copy()` | Independent copy |
| `kp.simplified()` | New simplified copy |
| `kp.rootless()` | Remove leading `/` |

### Resolution

```python
value = kp.get_obj(root_node)  # traverse and return the target value
```

Raises `AttributeError` or `KeyError` if the path does not exist. Wildcards are not supported in `get_obj` -- they are for pattern matching only.

### Matching

```python
pattern = KeyPath("/servers.*.port")
target = KeyPath("/servers.web.port")
pattern.match(target)  # True
```
