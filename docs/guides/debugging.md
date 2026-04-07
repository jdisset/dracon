# Debugging

Your config isn't what you expected. Something got overridden, a merge went wrong, an interpolation didn't resolve. Here's how to figure out what happened.

## dracon show: your main tool

`dracon show` loads config files and displays the result at various stages of processing.

### Compose only (default)

```bash
dracon show config.yaml
```

Shows the composed YAML tree after includes and merges, but before construction into Python objects. This is the most common starting point.

### Compose + construct + resolve

```bash
dracon show config.yaml -cr
```

The `-c` flag constructs Python objects. The `-r` flag resolves all lazy `${...}` interpolations. Together, `-cr` gives you the fully resolved config.

### Layer multiple files

```bash
dracon show +base.yaml +prod.yaml
```

Files are merged left-to-right, just like they would be in your program. This shows you what the final result looks like after layering.

### Select a subtree

```bash
dracon show config.yaml -cs database
```

The `-s` flag extracts a subtree by keypath. Output just the `database` section. Combine with `-c` to construct first.

### JSON output

```bash
dracon show config.yaml -cj
```

The `-j` flag outputs JSON instead of YAML (implies `-c`). Useful for piping to `jq`:

```bash
dracon show config.yaml -cjs database | jq '.port'
```

### Inject context variables

```bash
dracon show config.yaml ++env=prod ++region=us-east-1
```

The `++name=value` syntax sets context variables for `${...}` expressions.

### Override config values

```bash
dracon show config.yaml --database.port 5433
```

The `--path.to.key value` syntax overrides a specific config value at a dotted keypath.

### Permissive mode

```bash
dracon show config.yaml -crp
```

The `-p` flag enables permissive resolution: unresolvable `${...}` expressions are left as strings instead of raising errors. Useful when you want to see what resolves with partial context.

## Program-aware mode

If you have a `@dracon_program`, `dracon show` can inspect it directly:

```bash
dracon show myprogram
```

This discovers the program's Pydantic model, shows its defaults, and applies any auto-discovered config files.

```bash
dracon show myprogram --full      # expand all nested defaults
dracon show myprogram --schema    # dump the JSON Schema of the model
dracon show myprogram --diff      # show delta from bare defaults
```

## Tracing provenance

When you need to know *where* a value came from, use `--trace`:

```bash
dracon show config.yaml --trace db.port
```

This shows the provenance chain for `db.port`: which file defined it, which merge overwrote it, which CLI override changed it last.

Example output:

```
db.port:
  definition   base.yaml:12      5432
  file_layer   prod.yaml:8       5433
  cli_override --db.port=5434    5434
```

To trace everything at once:

```bash
dracon show config.yaml --trace-all
```

Tracing works on CLI programs too:

```bash
myapp +config.yaml --trace db.port
```

On a color terminal, the trace output gets syntax-highlighted with `rich`.

## Variable inspection

To see all defined variables (`!define`, `!set_default`, context vars) and their sources:

```bash
dracon show config.yaml --show-vars
```

Or from your program:

```bash
DRACON_SHOW_VARS=1 myapp +config.yaml
```

This prints a table to stderr showing each variable name, its value, and where it was defined.

## Error messages

Dracon errors include source context whenever possible.

### Source location

```
dracon.diagnostics.EvaluationError: Error evaluating expression: name 'typo' is not defined
  in config.yaml:14, column 8
  keypath: database.host

  ${typo}
    ^^^^^

Hint:
Variable 'typo' is not defined in this context
Did you mean: type?
```

Errors tell you the file, line, column, and the keypath where the problem occurred.

### Include traces

When an error happens inside an included file, you get the include chain:

```
CompositionError: Anchor 'missing' not found in document
  in db-config.yaml:3
  included from config.yaml:7
  included from base.yaml:2
```

### Error types

| Error | When |
|---|---|
| `CompositionError` | Something went wrong during composition (includes, merges, instructions) |
| `EvaluationError` | A `${...}` expression failed to evaluate |
| `UndefinedNameError` | A `${...}` expression referenced an undefined variable (subclass of `EvaluationError`) |
| `DraconError` | Base class for all Dracon errors; catch this to catch everything |
| `SchemaError` | JSON Schema or type validation issue |

## Python debugging

### Force-resolve all lazy values

```python
from dracon import resolve_all_lazy

config = dracon.load('config.yaml')

# resolve everything, raise on failures:
resolved = resolve_all_lazy(config)

# resolve what you can, leave the rest as strings:
partial = resolve_all_lazy(config, permissive=True)
```

### Inspect composed tree before construction

```python
from dracon import compose, construct, DraconLoader

loader = DraconLoader()
composed = loader.compose('config.yaml')

# composed is a CompositionResult; poke at composed.root (YAML node tree)
# then construct when ready:
result = loader.load_node(composed.root)
```

### Inspect a deferred node

```python
node = config['deferred_field']  # a DeferredNode

# compose it with context to see the intermediate state:
from dracon import compose
composed = compose(node, context={'key': 'value'})

# composed.root is the YAML node tree, pre-construction
# now construct:
from dracon import construct
result = construct(composed)
```

### Check what variables are in context

```python
loader = DraconLoader(context={'my_var': 42})
# loader.context is the full context dict, including builtins like getenv, Path, etc.
print(list(loader.context.keys()))
```
