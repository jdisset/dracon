# How-To: Inspect and Debug Configurations

`dracon-print` is Dracon's built-in tool for inspecting, composing, and dry-running configuration files from the command line. It lets you see exactly what your config looks like after all includes, merges, and instructions have been processed — without running your application.

## Basic Usage

Point it at a config file:

```bash
dracon-print config.yaml
```

This runs the **composition** phase only — includes are resolved, merges are applied, `!define`/`!if`/`!each` instructions are executed — but `${...}` interpolations remain as lazy nodes. This is useful for checking the structure of your config tree.

## Construct Mode

To fully construct the config into Python objects (evaluating interpolations, applying Pydantic validation, etc.), use `-c`:

```bash
dracon-print config.yaml -c
```

This runs both composition and construction, matching what `DraconLoader.load()` does.

## Layering Multiple Files

Pass multiple config files and they're merged left-to-right (later files override earlier ones), just like with any dracon CLI program:

```bash
dracon-print base.yaml overrides.yaml
```

You can also use the `+file` syntax:

```bash
dracon-print +base.yaml +prod.yaml
```

## Injecting Context Variables

Use `++` to set context variables available in `${...}` expressions:

```bash
dracon-print start.yaml ++runname experiment_1 ++base_config regression
```

Equals syntax works too:

```bash
dracon-print start.yaml ++runname=experiment_1
```

This is particularly useful for configs that use `!set_default` variables as an interface — you can test different variable combinations without changing any files.

## Resolving Lazy Values

Add `-r` to force evaluation of all `${...}` interpolations:

```bash
dracon-print config.yaml -r
```

!!! note
    `-r` automatically enables construct mode (`-c`), since resolution requires constructed Python objects.

If some interpolations depend on runtime values you can't provide, use `-p` (permissive) to leave unresolvable expressions as literal strings instead of erroring:

```bash
dracon-print config.yaml -rp ++known_var=42
# ${known_var} resolves to 42, ${unknown_var} stays as "${unknown_var}"
```

## Selecting a Subtree

Use `-s` (or `--select`) to extract a specific part of the config by keypath:

```bash
dracon-print config.yaml -c -s database
dracon-print config.yaml -c -s database.host
```

This is handy when you only care about one section of a large config.

## JSON Output

Use `-j` for JSON output (implies `-c`):

```bash
dracon-print config.yaml -j
```

Pipe-friendly — syntax highlighting is only applied when outputting to a terminal.

## Viewing Defined Variables

`--show-vars` prints a table of all variables (from `!define`, `++` CLI vars, and context) to stderr:

```bash
dracon-print config.yaml --show-vars
```

The table goes to stderr so it doesn't interfere with piping the config output.

## Combining Flags

Short flags can be combined:

```bash
dracon-print config.yaml -crj              # construct + resolve + json
dracon-print config.yaml -crs database     # construct + resolve + select
```

## Common Workflows

**Check what a complex layered config looks like after merging:**

```bash
dracon-print +defaults.yaml +env/prod.yaml +local.yaml -c
```

**Test a skeleton config with different variable combinations:**

```bash
dracon-print start.yaml ++dataset=set_A ++model=large -cr
dracon-print start.yaml ++dataset=set_B ++model=small -cr
```

**Extract and pipe a section as JSON:**

```bash
dracon-print config.yaml -cjs database | jq '.host'
```

**Debug why a value isn't what you expect:**

```bash
# See the composed tree (before construction)
dracon-print config.yaml -s problematic.path

# See the constructed value
dracon-print config.yaml -c -s problematic.path

# See with all interpolations forced
dracon-print config.yaml -cr -s problematic.path
```

**View all variables in scope:**

```bash
dracon-print config.yaml --show-vars ++my_var=test
```

## Composition Tracing

When you have multiple config layers and a value isn't what you expect, tracing tells you exactly where each value came from and what it replaced.

### Trace a single path

```bash
dracon-print base.yaml prod.yaml --trace db.port
# db.port = '5433'
#   1. = '5432'  <- base.yaml:3 (local key)
#   2. = '5433'  <- prod.yaml:3 (file layer 2)
```

### Trace all values

```bash
dracon-print base.yaml prod.yaml --trace-all
```

Shows every leaf value with its provenance. Values with multiple sources show the full chain.

### Tracing in @dracon_program CLIs

Every program built with `@dracon_program` gets `--trace` and `--trace-all` built in:

```bash
my-program +base.yaml +prod.yaml --trace-all
my-program +base.yaml --trace server.port
```

### Tracing via Python API

```python
from dracon import DraconLoader

loader = DraconLoader(trace=True)
cr = loader.compose(['base.yaml', 'prod.yaml'])

# single path
for entry in cr.trace.get("db.port"):
    print(f"{entry.value} <- {entry.source} ({entry.via})")

# all paths
for path, entries in cr.trace_all().items():
    print(f"{path}: {len(entries)} steps")
```

### Tracing via environment variable

Set `DRACON_TRACE=1` to enable tracing globally without changing code or CLI flags. When tracing is enabled and an error occurs, error messages include the provenance chain showing where the bad value came from.

### What gets traced

| Operation | `via` value | What it records |
|-----------|-------------|-----------------|
| Value defined in file | `definition` | File, line |
| File layer merge (`load([a, b])`) | `file_layer` | Layer index, source file |
| `!include` | `include` | Include path |
| `<<:` merge | `merge` | Merge strategy, winner/loser |
| `!if` branch | `if_branch` | Which branch, condition |
| `!each` expansion | `each_expansion` | Loop variable |
| CLI override (`--key=val`) | `cli_override` | Flag used |
