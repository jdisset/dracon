# `dracon` CLI Reference

Unified command-line tool for inspecting configurations and managing shell completions.

```
dracon show [OPTIONS] TARGET [TARGET ...]
dracon completions {bash|zsh|fish|install}
```

!!! note
    `dracon show` replaces the old `dracon-print` command. Migration: `dracon-print X` -> `dracon show X`.

## `dracon show`

### Two Modes

Mode is auto-detected from the first argument:

- **Raw YAML mode**: first target is a `.yaml` file or starts with `+` -- compose, construct, resolve raw YAML.
- **Program-aware mode**: first target is an installed `@dracon_program` name -- resolves through the full program stack (ConfigFile auto-discovery, model defaults, layering).

### Options

| Flag | Long Form | Description |
|------|-----------|-------------|
| `-c` | `--construct` | Fully construct into Python objects (default: compose only) |
| `-r` | `--resolve` | Resolve all lazy `${...}` interpolations. Implies `-c`. |
| `-p` | `--permissive` | Leave unresolvable `${...}` as strings instead of erroring. Use with `-r`. |
| `-s` | `--select PATH` | Extract subtree at keypath (e.g., `database.host`) |
| `-j` | `--json` | Output as JSON. Implies `-c`. |
| | `--full` | Exhaustive config template with all nested defaults expanded (program-aware mode) |
| | `--schema` | Emit JSON Schema for a program's model (program-aware mode only) |
| | `--no-docs` | Suppress inline field descriptions (program-aware mode) |
| | `--depth N` | Limit recursion into nested models |
| | `--show-vars` | Print table of all defined variables to stderr |
| | `--trace PATH` | Show provenance chain for a specific config path |
| | `--trace-all` | Show provenance for all values |
| `-v` | `--verbose` | Enable debug logging |

Short flags can be combined: `-crj` is equivalent to `-c -r -j`.

### Context Variables

Inject variables available in `${...}` expressions.

| Syntax | Example |
|--------|---------|
| `++name value` | `++runname experiment_1` |
| `++name=value` | `++runname=experiment_1` |
| `--define.name value` | `--define.runname experiment_1` |

Values are parsed as YAML, so `++count=5` becomes an integer, `++tags="[a,b,c]"` becomes a list.

### Output Modes

| Mode | Flag | Description |
|------|------|-------------|
| **Compose** (default) | _(none)_ | YAML tree after composition. `${...}` remain lazy. |
| **Construct** | `-c` | Fully construct into Python objects. |
| **Resolve** | `-r` | Construct + force all lazy values. |
| **Permissive** | `-rp` | Resolve what can be resolved, leave the rest as strings. |

### Tracing

| Flag | Description |
|------|-------------|
| `--trace PATH` | Provenance chain for a specific config path (e.g., `db.port`) |
| `--trace-all` | Provenance for all values |

Reveals where each value came from -- which file, what overrode it, and through which operation. Uses colored rich output on TTY. Also available via `DRACON_TRACE=1` env var.

### Examples

```bash
# ── Raw YAML mode ──────────────────────────────────────────

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

# Trace where a value came from across layers
dracon show base.yaml prod.yaml --trace db.port

# ── Program-aware mode ─────────────────────────────────────

# Show a program's default config
dracon show broodmon

# Exhaustive template with all nested defaults
dracon show broodmon --full

# Layered config with overrides
dracon show broodmon +prod.yaml

# JSON Schema of the model
dracon show broodmon --schema

# Select a subtree
dracon show broodmon --select execution
```

## `dracon completions`

Universal shell completion for all `@dracon_program` CLIs.

```bash
dracon completions install    # auto-detect shell, write cache, add to rc
dracon completions bash       # emit bash completion script
dracon completions zsh        # emit zsh completion script
dracon completions fish       # emit fish completion script
```

### How it works

`install` writes a cached completion script to `~/.dracon/completions.{shell}` and adds a source line to the shell rc file. A background process regenerates the cache hourly to pick up newly installed programs.

### Performance

Completions are handled by a lightweight module (`dracon_complete.py`) that avoids importing dracon or any program modules for common cases:

| Completion type | Method | Speed |
|----------------|--------|-------|
| `+file` paths | Native shell globbing (zsh `_files`) | 0ms Python |
| `--flags` | Regex source scan of program module | ~50ms |
| Subcommands | Regex scan for `@subcommand` decorators | ~50ms |
| Dynamic (job names, etc.) | Imports program, calls `__dracon_complete__` | ~500ms |
| Unknown prefix | Returns nothing | ~50ms |

### Dynamic completions

Programs can define context-aware completions by adding a `__dracon_complete__` static method:

```python
@dracon_program(name="myapp")
class MyApp(BaseModel):
    @staticmethod
    def __dracon_complete__(prefix: str, tokens: list[str]) -> list[str]:
        if tokens[-2] == "--name":
            return _list_available_names(prefix)
        subcmd = next((t for t in tokens[1:] if t in SUBCMDS), None)
        if subcmd in ("attach", "kill"):
            return _query_running_jobs(prefix)
        return []
```

The fast handler only imports the program when it detects `__dracon_complete__` in the source.

## Python API

The show logic is also usable programmatically:

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
