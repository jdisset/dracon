# dracon CLI

Command-line tool for inspecting and resolving Dracon configurations.

---

## dracon show

```
dracon show [OPTIONS] TARGET [TARGET ...]
```

Load one or more Dracon config files, apply composition (merging, includes, instructions), and display the result. Files are layered left to right; later files override earlier ones.

### Mode Auto-Detection

The first positional argument determines the mode:

- **Raw YAML mode** (default): when the first argument ends in `.yaml`/`.yml` or starts with `+`
- **Program-aware mode**: when the first argument is recognized as a `@dracon_program` name. Shows model defaults, auto-discovered config files, and supports `--full` and `--schema`.

### Options

| Flag | Description |
|------|-------------|
| `-c`, `--construct` | Fully construct into Python objects. Default: compose only (shows the YAML node tree). |
| `-r`, `--resolve` | Resolve all lazy interpolations. Implies `-c`. |
| `-p`, `--permissive` | Leave unresolvable `${...}` as strings instead of erroring. Use with `-r`. |
| `-s PATH`, `--select PATH` | Extract a subtree at a dotted keypath (e.g. `database.host`). |
| `-j`, `--json` | Output as JSON. Implies `-c`. |
| `--str-output` | Output raw `str()` instead of YAML. |
| `-f PATH`, `--file PATH` | Config file (legacy form; prefer positional args). |
| `--full` | Exhaustive config template with all nested defaults expanded. Program-aware mode only. |
| `--schema` | Emit JSON Schema for a program's model. Program-aware mode only. |
| `--show-vars` | Print table of all defined variables to stderr. |
| `--trace PATH` | Show composition provenance chain for a dotted keypath. |
| `--trace-all` | Show provenance for all values. |
| `-v`, `--verbose` | Enable debug logging. |
| `-h`, `--help` | Show help. |
| `--version` | Show version. |

Short flags cannot be combined: use `-c -r -j`, not `-crj`.

### Context Injection

Set variables for `${...}` expressions:

```
dracon show config.yaml ++env production
dracon show config.yaml ++env=production
dracon show config.yaml --define.env production
dracon show config.yaml --define.env=production
```

### Config Overrides

Override specific values at dotted keypaths:

```
dracon show config.yaml --database.port 5433
dracon show config.yaml --database.port=5433
```

---

## dracon completions

```
dracon completions {bash|zsh|fish|install}
```

### Subcommands

| Command | Description |
|---------|-------------|
| `bash` | Print bash completion script to stdout. |
| `zsh` | Print zsh completion script to stdout. |
| `fish` | Print fish completion script to stdout. |
| `install` | Auto-detect the current shell, generate the completion script, write it to the appropriate cache directory, and add the source line to the shell's rc file. |

### Performance

Completions use a lightweight fast-path module that avoids importing the full Dracon stack. Target latency is under 50ms per completion request.

### Dynamic Completions

Programs decorated with `@dracon_program` can provide custom completions by defining a static method:

```python
@dracon_program(name="mytool")
class Config(BaseModel):
    target: str

    @staticmethod
    def __dracon_complete__(prefix: str, tokens: list[str]) -> list[str]:
        # return candidates matching prefix
        return [t for t in ["train", "eval", "test"] if t.startswith(prefix)]
```

The method receives the current prefix being completed and the full token list, and returns a list of candidate strings.

---

## Python API

### DraconPrint

The core class behind `dracon show`. Can be used programmatically:

```python
from dracon.cli import DraconPrint

printer = DraconPrint(
    config_files=["config.yaml"],
    construct=True,
    resolve=True,
    json_output=True,
    context={"env": "production"},
    overrides={"db.port": 5433},
)
output = printer.run()
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `config_files` | `list[str]` | Config file paths. |
| `construct` | `bool` | Construct into Python objects. |
| `resolve` | `bool` | Resolve lazy values. |
| `permissive` | `bool` | Leave unresolvable as strings. |
| `select` | `str` | Keypath to extract. |
| `json_output` | `bool` | Format as JSON. |
| `str_output` | `bool` | Format as `str()`. |
| `show_vars` | `bool` | Print variables table to stderr. |
| `verbose` | `bool` | Debug logging. |
| `context` | `dict` | Context variables. |
| `overrides` | `dict` | Dotted-path overrides. |
| `trace` | `str` | Trace a single keypath. |
| `trace_all` | `bool` | Trace all values. |

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DRACON_TRACE` | Set to `1`, `true`, or `yes` to enable composition tracing globally (same as `trace=True`). |
| `DRACON_SHOW_VARS` | Set to `1` to print a table of all defined variables and their sources to stderr. |
| `ENABLE_FTRACE` | Enable internal function tracing for debugging Dracon itself. |
| `ENABLE_SER_DEBUG` | Enable serialization debugging (deepcopy diagnostics). |
