# `dracon show` Reference

Command-line tool for inspecting, composing, and dry-running Dracon configuration files.

```
dracon show [OPTIONS] CONFIG [CONFIG ...]
```

!!! note
    `dracon show` replaces the old `dracon-print` command. If you have scripts using `dracon-print`, change them to `dracon show`.

## Arguments

| Argument | Description |
|----------|-------------|
| `CONFIG` | One or more config file paths. Layered left-to-right (later overrides earlier). Accepts bare paths or `+file` syntax. |

## Options

| Flag | Long Form | Description |
|------|-----------|-------------|
| `-c` | `--construct` | Fully construct into Python objects (default: compose only) |
| `-r` | `--resolve` | Resolve all lazy `${...}` interpolations. Implies `-c`. |
| `-p` | `--permissive` | Leave unresolvable `${...}` as strings instead of erroring. Use with `-r`. |
| `-s` | `--select PATH` | Extract subtree at keypath (e.g., `database.host`) |
| `-j` | `--json` | Output as JSON. Implies `-c`. |
| | `--str-output` | Output raw `str()` representation instead of YAML |
| | `--show-vars` | Print table of all defined variables to stderr |
| | `--schema` | Emit JSON Schema for a program's model (program-aware mode only) |
| | `--diff` | Show delta from bare defaults (program-aware mode only) |
| | `--depth N` | Limit recursion into nested models |
| | `--no-docs` | Suppress inline field descriptions (program-aware mode) |
| `-v` | `--verbose` | Enable debug logging |
| `-h` | `--help` | Show help message |
| | `--version` | Show version |

Short flags can be combined: `-crj` is equivalent to `-c -r -j`.

## Two Modes

`dracon show` detects the mode from the first argument:

- **Raw YAML mode**: if the first target is a `.yaml` file path or starts with `+`, it works like the old `dracon-print` -- compose, construct, resolve raw YAML.
- **Program-aware mode**: if the first target is a program name (an installed `@dracon_program`), it resolves through the full program stack: `ConfigFile` auto-discovery, model defaults, CLI arg parsing, layering.

## Context Variables

Inject variables available in `${...}` expressions inside the loaded configs.

| Syntax | Example |
|--------|---------|
| `++name value` | `++runname experiment_1` |
| `++name=value` | `++runname=experiment_1` |
| `--define.name value` | `--define.runname experiment_1` |

Values are parsed as YAML, so `++count=5` becomes an integer, `++tags="[a,b,c]"` becomes a list.

## Output Modes

| Mode | Flag | Description |
|------|------|-------------|
| **Compose** (default) | _(none)_ | Shows the YAML tree after composition (includes resolved, merges applied, instructions executed). `${...}` interpolations remain as lazy nodes. |
| **Construct** | `-c` | Fully constructs into Python objects, evaluating interpolations. Equivalent to `DraconLoader.load()`. |
| **Resolve** | `-r` | Like construct, but also forces evaluation of all remaining lazy values. |
| **Permissive** | `-rp` | Resolve what can be resolved, leave the rest as `${...}` strings. |

## Tracing

| Flag | Description |
|------|-------------|
| `--trace PATH` | Show the provenance chain for a specific config path (e.g., `db.port`) |
| `--trace-all` | Show provenance for all values |

Tracing reveals **where each value came from** — which file defined it, what overrode it, and through which operation (include, merge, file layer, `!if` branch, etc.). When outputting to a terminal, trace output uses colored rich panels/tables.

Can also be enabled via the `DRACON_TRACE=1` environment variable.

## Output Formats

| Format | Flag | Notes |
|--------|------|-------|
| YAML | _(default)_ | Syntax-highlighted when outputting to a terminal. Respects `NO_COLOR` env var. |
| JSON | `-j` | Implies construct mode. Indented, pipe-friendly. |
| Raw string | `--str-output` | Python `str()` representation. |

## Examples

```bash
# Compose a single file
dracon show config.yaml

# Construct with full evaluation
dracon show config.yaml -c

# Layer multiple files, construct, and resolve
dracon show base.yaml prod.yaml -cr

# Inject context variables and get JSON output
dracon show start.yaml ++runname=exp1 ++model=large -cj

# Select a subtree
dracon show config.yaml -c -s database.connections

# Permissive resolve (partial evaluation)
dracon show config.yaml -rp ++known_var=42

# Show defined variables
dracon show config.yaml --show-vars

# Debug with verbose logging
dracon show config.yaml -v

# Dracon +file convention
dracon show +defaults.yaml +env/prod.yaml +local.yaml

# Pipe JSON subtree to jq
dracon show config.yaml -cjs database | jq '.host'

# Trace where a value came from across layers
dracon show base.yaml prod.yaml --trace db.port

# Trace all values
dracon show base.yaml prod.yaml --trace-all

# Program-aware mode: show a program's resolved config
dracon show myprogram

# Program-aware: emit JSON Schema for a program
dracon show myprogram --schema
```

## Python API

The tool's core logic is also usable programmatically:

```python
from dracon.cli import DraconPrint

printer = DraconPrint(
    config_files=["base.yaml", "override.yaml"],
    construct=True,
    resolve=True,
    permissive=True,
    select="database",
    json_output=True,
    context={"env": "prod"},
)
output = printer.run()
```
