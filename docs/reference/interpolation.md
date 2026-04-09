# Interpolation

Expression evaluation inside YAML values.

---

## Syntax

### `${...}` and `$(...)`

Identical behavior. Both delimit a lazy expression that is evaluated during construction.

```yaml
port: ${base_port + 1}
greeting: "Hello, $(name)!"
```

When the entire YAML value is a single interpolation, the result retains its native type (int, list, dict, etc.). When mixed with literal text, the result is stringified.

### `$VAR` shorthand

When `enable_shorthand_vars=True` (the default), bare `$VAR` tokens are auto-converted to `${VAR}` before evaluation.

```yaml
path: $HOME/.config    # equivalent to: ${HOME}/.config
```

### Escaping

Two ways to prevent interpolation and produce a literal `${...}` in the output:

```yaml
# backslash escape
template: \${not_evaluated}    # -> ${not_evaluated}

# double-dollar escape
template: $${not_evaluated}    # -> ${not_evaluated}
```

Both work for all interpolation forms:

| You write | Output |
|-----------|--------|
| `\${expr}` | `${expr}` |
| `$${expr}` | `${expr}` |
| `\$(expr)` | `$(expr)` |
| `$$(expr)` | `$(expr)` |
| `\$VAR` | `$VAR` |
| `$$` (anywhere) | `$` |

The `$$` form is often easier since it avoids interactions with YAML's own backslash handling. Both work in strings that also contain real interpolations:

```yaml
!define name: world

# mix resolved and passthrough expressions in the same value
msg: "hello ${name}, metric=$${value}"   # -> hello world, metric=${value}
```

This is useful when a host application needs certain `${...}` tokens to survive Dracon construction for later runtime resolution.

---

## Expression Evaluation

Expressions support full Python syntax, evaluated via one of two engines:

| Engine | Safety | Notes |
|--------|--------|-------|
| `asteval` (default) | Sandboxed, no imports, no file access | Sufficient for most configs |
| `eval` | Full Python `eval()` | Use when you need builtins, imports, etc. |

Set via `interpolation_engine` in `DraconLoader` or `@dracon_program`.

Expressions can use any variable in the current context: built-in functions, `!define`d variables, file context vars, and CLI-injected values.

### Examples

```yaml
!define items: [1, 2, 3]

count: ${len(items)}
doubled: ${[x * 2 for x in items]}
env: ${getenv('HOME', '/root')}
stamp: ${now('%Y%m%d')}
conditional: ${'prod' if env == 'production' else 'dev'}
```

---

## Value References

### `@path` -- constructed value reference

Retrieves the final constructed value at a keypath, resolved relative to the current node's parent.

```yaml
db:
  port: 5432
  url: "postgres://localhost:${@port}/mydb"
```

Here `@port` is a relative reference to the sibling key `port` within the same mapping. You could also write `${@/db.port}` as an absolute path from the document root. Using `@db.port` from inside `db` would incorrectly resolve to `/db/db.port`.

Absolute paths (starting with `/`) start from the document root. Relative paths are resolved from the expression's location.

### `&path` -- node copy reference

Deep-copies the raw YAML node at composition time (before construction). Must appear inside `${...}`.

```yaml
defaults: &base
  timeout: 30
  retries: 3

service_a:
  settings: ${&base}  # deep copy of the raw node
```

Also works with anchors: `${&anchor_name}` or `${&anchor_name.sub.key}`.

Context can be passed to the copied node: `${&path:var1=expr1,var2=expr2}`.

---

## Built-in Functions

Available in all interpolation expressions. See [Loader API - Built-in Context](loader-api.md#functions) for the full table.

| Function | Description |
|----------|-------------|
| `getenv(name, default)` | Environment variable |
| `getcwd()` | Current working directory |
| `listdir(path)` | Directory listing |
| `join(*parts)` | Path joining |
| `basename(path)` | Filename from path |
| `dirname(path)` | Directory from path |
| `expanduser(path)` | Expand `~` |
| `isfile(path)` | Check file exists |
| `isdir(path)` | Check directory exists |
| `Path` | `pathlib.Path` constructor |
| `now(fmt)` | Current timestamp |
| `construct(node)` | Construct a raw node |

When `numpy` is installed, `np` is also available.

---

## Permissive Mode

When `permissive=True`, unresolvable expressions are left as strings instead of raising `UndefinedNameError`.

```python
result = dracon.resolve_all_lazy(obj, permissive=True)
```

Partially resolvable expressions are simplified: if some variables are known, they are folded, and the remaining unknowns stay as `${...}`.

---

## Two-Phase Resolution

During construction, interpolations are evaluated twice with a growing context. The first pass resolves what it can; the second pass picks up values that depended on results from the first pass. This handles most forward-reference scenarios without explicit ordering.

Recursion depth is capped at 5 levels to catch circular references.

---

## Error Types

### `UndefinedNameError`

Raised when an expression references a name not in the current context. In permissive mode, caught and left as a string.

Includes: the undefined name, source context (file/line), the full expression, and available symbol names for "did you mean?" suggestions.

### `EvaluationError`

Raised for any other evaluation failure (syntax errors, type errors, attribute errors, etc.).

Includes: the expression, source context, a visual pointer to the error location (when available), and hints for common mistakes.

---

## evaluate_expression API

Low-level function for evaluating interpolation expressions programmatically.

```python
from dracon import evaluate_expression

result = evaluate_expression(
    expr="Hello, ${name}!",
    current_path="/",
    root_obj=None,
    context={"name": "world"},
    engine="asteval",
    permissive=False,
)
```

| Parameter | Description |
|-----------|-------------|
| `expr` | The string to evaluate (may contain `${...}` blocks). |
| `current_path` | KeyPath for `@` references. Default `"/"`. |
| `root_obj` | Root object for `@` path resolution. |
| `context` | Variables available in expressions. |
| `engine` | `'asteval'` or `'eval'`. |
| `permissive` | Leave unresolvable as strings. |
| `enable_shorthand_vars` | Convert `$VAR` to `${VAR}`. Default `True`. |
| `source_context` | `SourceContext` for error messages. |
| `allow_recurse` | Max recursion depth. Default `5`. |
