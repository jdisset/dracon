# Include Schemes

Loaders for `!include` directives. Each scheme handles a different content source.

---

## file:path

Load from the filesystem.

```yaml
database: !include file:db.yaml
nested: !include file:configs/nested/settings.yaml
home: !include file:~/defaults.yaml
```

- Paths are resolved relative to the current working directory.
- Extension search: if the exact path is not found, Dracon tries `.yaml` and `.yml` suffixes automatically.
- File context variables (`DIR`, `FILE`, `FILE_PATH`, `FILE_STEM`, `FILE_EXT`, `FILE_LOAD_TIME`, `FILE_LOAD_TIME_UNIX`, `FILE_LOAD_TIME_UNIX_MS`, `FILE_SIZE`) are set and available in `${...}` expressions within the loaded file.
- `~` is expanded via `Path.expanduser()`.

---

## pkg:package:path

Load from a Python package's bundled resources via `importlib.resources`.

```yaml
defaults: !include pkg:mypackage:data/defaults.yaml
```

Format: `pkg:PACKAGE_NAME:RESOURCE_PATH`

---

## env:VAR_NAME

Load the value of an environment variable as a YAML string.

```yaml
api_key: !include env:API_KEY
```

The value is parsed as YAML, so `env:PORT` where `PORT=8080` yields an integer, not a string.

Raises `FileNotFoundError` if the variable is not set. Use `!include?` for optional env vars.

---

## var:var_name

Load a value from the current interpolation context (in-memory).

```yaml
!define shared_config:
  timeout: 30

service:
  settings: !include var:shared_config
```

The variable is looked up in the loader's context dict. Useful for including values defined by `!define` or injected programmatically.

---

## raw:path

Load a file as plain text without YAML parsing. The raw string becomes a scalar node.

```yaml
readme: !include raw:README.md
template: !include raw:templates/email.html
```

Same path resolution and extension behavior as `file:`.

---

## rawpkg:package:path

Load a package resource as plain text without YAML parsing.

```yaml
schema: !include rawpkg:mypackage:schemas/v1.json
```

Format: `rawpkg:PACKAGE_NAME:RESOURCE_PATH`

---

## cascade:path

Walk up the directory tree from the current file's `DIR` (or CWD), collecting all files matching the relative path. Files are merged root-first, so the closest file has the highest priority.

```yaml
settings: !include cascade:.myapp.yaml
```

This finds every `.myapp.yaml` from the current directory up to the filesystem root, then merges them with the outermost (root-level) file as the base and the closest file winning on conflicts.

### Custom merge strategy

```yaml
settings: !include cascade:{>+}[>~]:.myapp.yaml
```

The merge key spec is prepended before the path, enclosed in `{...}` and/or `[...]`, followed by `:`.

Default merge strategy: `<<{<+}[<~]` (recursive append, new wins).

### Path requirements

- Must be a relative path (absolute paths raise `ValueError`).
- Raises `FileNotFoundError` if no matching files are found anywhere in the directory hierarchy.

---

## py:reference

Load a Python symbol (class, function, module attribute) into dracon's symbol table. Unifies Python-side resolution with the rest of `!include` — same grammar, same selector, same layering.

```yaml
# dotted module path — uses normal Python import
!define Tensor: !include py:torch@Tensor

# the module itself as a namespace; the @selector picks the attribute
!define sqrt: !include py:math@sqrt

# attribute shorthand: when the dotted path is not importable as a module,
# the last segment is treated as a name on the prefix
!define sqrt: !include py:math.sqrt

# file path — loaded via importlib.util, no sys.path mutation
!define Helper: !include py:$DIR/helpers.py@Helper

# the bound symbol is a first-class tag like any other
h: !Helper { cfg: 1 }
```

**Forms**

| Path | Behaviour |
|------|-----------|
| `module.path` | Imports the module. Returns a namespace mapping of public names. |
| `module.path@Name` | Imports the module; `@Name` picks that attribute. |
| `module.attr` (not importable as module) | Falls back to `module` + `getattr(..., attr)`. Single symbol. |
| `/abs/path.py` or `$DIR/path.py` | Loads the file directly with `importlib.util.spec_from_file_location`. |

**Public-name filter.** Namespace-form includes (no `@selector`) only expose names in `__all__`, or — when `__all__` is absent — names that don't start with an underscore. Use `!fn:py:mod._name` for explicit access to private attributes.

**Use inside `!fn:`.** Any scheme URI can be used as the `!fn:` target, so `!fn:py:torch.nn.Linear { in: 10 }` is the scheme-qualified equivalent of `!fn:torch.nn.Linear { in: 10 }`. The bare dotted form `!fn:torch.nn.Linear` stays as shorthand for `!fn:py:torch.nn.Linear`.

---

## Selectors

Any scheme can include a `@keypath` selector to extract a subtree from the loaded content:

```yaml
db_host: !include file:config.yaml@database.host
port: !include pkg:mypackage:defaults.yaml@server.port
```

The keypath is applied after loading and parsing. See [KeyPaths](keypaths.md) for path syntax.

---

## Custom Loaders

Register additional schemes via `custom_loaders` in `DraconLoader`:

```python
def read_from_s3(path, node=None, draconloader=None, **_):
    content = boto3.client('s3').get_object(...)['Body'].read().decode()
    return content, {}  # (yaml_string, context_dict)

loader = DraconLoader(custom_loaders={"s3": read_from_s3})
```

A loader function receives:

| Argument | Description |
|----------|-------------|
| `path` | Everything after the `scheme:` prefix |
| `node` | The `IncludeNode` (access `.context`, `.value`, etc.) |
| `draconloader` | The current `DraconLoader` instance |

It must return a tuple of `(content, context_dict)` where:

- `content` is either a YAML string (will be parsed) or a `CompositionResult` (used directly)
- `context_dict` is a dict of context variables to inject (can be empty)
