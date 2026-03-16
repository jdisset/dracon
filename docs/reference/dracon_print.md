# `dracon-print` Reference

Command-line tool for inspecting, composing, and dry-running Dracon configuration files.

```
dracon-print [OPTIONS] CONFIG [CONFIG ...]
```

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
| `-v` | `--verbose` | Enable debug logging |
| `-f` | `--file PATH` | Config file (legacy syntax, prefer positional args) |
| `-h` | `--help` | Show help message |
| | `--version` | Show version |

Short flags can be combined: `-crj` is equivalent to `-c -r -j`.

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

## Output Formats

| Format | Flag | Notes |
|--------|------|-------|
| YAML | _(default)_ | Syntax-highlighted when outputting to a terminal. Respects `NO_COLOR` env var. |
| JSON | `-j` | Implies construct mode. Indented, pipe-friendly. |
| Raw string | `--str-output` | Python `str()` representation. |

## Examples

```bash
# Compose a single file
dracon-print config.yaml

# Construct with full evaluation
dracon-print config.yaml -c

# Layer multiple files, construct, and resolve
dracon-print base.yaml prod.yaml -cr

# Inject context variables and get JSON output
dracon-print start.yaml ++runname=exp1 ++model=large -cj

# Select a subtree
dracon-print config.yaml -c -s database.connections

# Permissive resolve (partial evaluation)
dracon-print config.yaml -rp ++known_var=42

# Show defined variables
dracon-print config.yaml --show-vars

# Debug with verbose logging
dracon-print config.yaml -v

# Dracon +file convention
dracon-print +defaults.yaml +env/prod.yaml +local.yaml

# Pipe JSON subtree to jq
dracon-print config.yaml -cjs database | jq '.host'
```

## Python API

The tool's core logic is also usable programmatically:

```python
from dracon_print import DraconPrint

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
