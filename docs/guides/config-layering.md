# Config Layering

You have multiple environments, shared defaults, per-project overrides, and optional local tweaks. Here's how to layer them.

## The mental model

Think of config layering as a stack of transparencies. Each layer adds or overrides values. Later layers win. You start with a base, stack environment-specific overrides on top, then let the user's CLI flags override everything.

```
base.yaml              (lowest priority)
env/prod.yaml          (overrides base)
~/.myapp/config.yaml   (auto-discovered, user defaults)
+extra.yaml            (CLI file arg)
--flag value           (highest priority)
```

## Multi-file loading

### From Python

Pass a list of paths to `dracon.load()`. They merge left to right:

```python
import dracon

config = dracon.load(['base.yaml', 'prod.yaml'])
```

`prod.yaml` overrides `base.yaml` wherever they overlap.

### From the CLI

Use the `+file` syntax. Each `+file` is a layer:

```bash
myapp +base.yaml +prod.yaml --check-interval 10
```

Same idea: `prod.yaml` overrides `base.yaml`, and `--check-interval` overrides both.

### Selectors with @

You can extract a subtree from a file using `@`:

```bash
myapp +full-config.yaml@database
```

This loads `full-config.yaml`, pulls out just the `database` key, and uses that as the config. Works in Python too:

```python
config = dracon.load(['full-config.yaml@database'])
```

Selectors support nested paths: `+file.yaml@services.api` extracts `services` then `api`.

## Include schemes

Inside YAML, `!include` pulls in content from various sources. The part before the colon is the scheme:

| Scheme | What it does | Example |
|--------|-------------|---------|
| `file:` | Local filesystem, `$DIR` for relative paths | `!include file:$DIR/db.yaml` |
| `pkg:` | Python package resources | `!include pkg:mylib/defaults.yaml` |
| `env:` | Environment variable value | `!include env:MY_CONFIG_VAR` |
| `var:` | In-memory context variable | `!include var:injected_config` |
| `cascade:` | Walk up directories, merge all matches | `!include cascade:.myapp.yaml` |
| `py:` | Python symbol (dotted module or file path) | `!include py:torch@Tensor` |

`$DIR` always resolves to the directory of the file containing the `!include`. This means relative paths work regardless of where you run from.

For full details on each scheme, see the reference.

### Python symbols via `py:`

The `py:` scheme pulls a Python symbol (class, function, module attribute) into dracon's symbol table the same way other schemes pull YAML content. It replaces the need for `sys.path` hacks and unifies symbol resolution under the same grammar as the rest of `!include`:

```yaml
# dotted path — uses normal Python import
!define Tensor: !include py:torch@Tensor
!define sqrt:   !include py:math.sqrt         # no selector needed for a single attr

# file path — loaded via importlib.util, no sys.path mutation
!define Helper: !include py:$DIR/helpers.py@Helper

# the bound symbol is a first-class tag like any other
thing: !Helper { cfg: 1 }
```

The same scheme URI grammar works inside `!fn:` for partial application:

```yaml
loss: !fn:py:torch.nn.CrossEntropyLoss { weight: 0.7 }
fh:   !fn:py:$DIR/helpers.py@Helper { cfg: 1 }
```

The bare `!fn:dotted.path` form (no explicit scheme) is shorthand for `!fn:py:dotted.path`, so existing `!fn:math.sqrt` style stays unchanged.

**Public-name filter.** `!include py:mod` with no selector returns the module's public names as a namespace mapping (honouring `__all__` when present, otherwise filtering underscore-prefixed names). `!include py:mod@_private` therefore fails for private names; use `!fn:py:mod._private` when you need explicit access.

## Cascade includes

The `cascade:` scheme walks up from the current working directory toward the filesystem root, collecting every file that matches the given relative path. It merges them root-first, so the closest file (nearest to CWD) has the highest priority.

```yaml
# loads .myapp.yaml from every parent directory, merges them
<<{>+}: !include cascade:.myapp.yaml
```

This is good for monorepos where each subdirectory can have its own `.myapp.yaml` that inherits from a repo-wide one.

### ConfigFile and auto-discovery

When using `@dracon_program`, you can declare config files that get auto-discovered before any CLI args are processed:

```python
from dracon import dracon_program, ConfigFile

@dracon_program(
    name="myapp",
    config_files=[
        ConfigFile("~/.myapp/config.yaml"),
        ConfigFile(".myapp.yaml", search_parents=True),
    ],
)
class MyConfig(BaseModel):
    db_host: str = "localhost"
    port: int = 5432
```

- `ConfigFile("~/.myapp/config.yaml")` loads from the user's home directory if the file exists. Silently skipped if missing.
- `ConfigFile(".myapp.yaml", search_parents=True)` uses the cascade loader, walking up from CWD and merging all matches.
- `ConfigFile("required.yaml", required=True)` raises an error if the file is not found.
- `ConfigFile("full.yaml", selector="database")` extracts the `database` subtree.

Auto-discovered configs are prepended as `+file` before the user's CLI args. So the precedence is:

```
model defaults  <  auto-discovered  <  +file args  <  --flags
```

### Real-world pattern

A CLI tool with home-dir defaults and project-local overrides:

```python
@dracon_program(
    name="deploy",
    config_files=[
        ConfigFile("~/.deploy/config.yaml"),           # user-wide defaults
        ConfigFile(".deploy.yaml", search_parents=True), # project cascade
    ],
)
class DeployConfig(BaseModel):
    target: str = "staging"
    replicas: int = 1
```

A developer runs `deploy` from `/repo/services/api/`. The cascade finds `.deploy.yaml` in `/repo/` and `/repo/services/api/`, merges them (repo-wide first, project-local wins), then layers the home-dir config underneath. CLI flags override everything.

## Merge strategies

Merge keys control how two mappings or lists combine. The syntax is `<<{dict_opts}[list_opts]:`.

### Quick reference

| Key | Dict behavior | List behavior | Use case |
|-----|--------------|---------------|----------|
| `<<:` | Append new keys, existing wins, deep merge | Existing wins, replace | Standard YAML-like merge |
| `<<{<+}:` | New wins, deep merge | (default list) | Included content overrides me |
| `<<{>+}:` | Existing wins, deep merge | (default list) | I override the included content |
| `<<{<~}:` | New wins, shallow replace | (default list) | Full key replacement |
| `<<[+]:` | (default dict) | Append lists | Combine lists |
| `<<[<+]:` | (default dict) | New wins, append | Override + combine lists |
| `<<@path:` | Merge into subtree at `path` | - | Target a nested key |

Symbols: `<` = new wins, `>` = existing wins, `+` = deep merge / append, `~` = replace.

### Example: override with deep merge

The most common pattern. Your environment file overrides the base, but nested dicts merge field by field:

```yaml
# env/prod.yaml
check_interval: 15
database:
  host: db.prod.internal

<<{>+}: !include file:$DIR/../base.yaml
```

`{>+}` means "I (prod.yaml) win conflicts, merge dicts recursively." So `database.host` comes from prod, but `database.port` and `database.name` are kept from base.

### Example: append to a list

```yaml
# extra-sites.yaml
sites:
  - https://new-site.com

<<[+]: !include file:$DIR/base.yaml
```

`[+]` appends the `sites` list from base into the current one, instead of replacing it.

### Example: merge into a subtree

```yaml
# Apply overrides specifically to the database subtree
<<@database: !include file:$DIR/db-overrides.yaml
```

The contents of `db-overrides.yaml` get merged into the `database` key of the current mapping.

## Context propagation with (<)

By default, variables defined in a merged-in file don't leak into the parent. If you need them to, use `(<)`:

```yaml
# settings.yaml
!define version: "2.0"
api_url: "https://api.example.com/v${version}"
```

```yaml
# main.yaml
<<{>+}(<): !include file:$DIR/settings.yaml

# version is now available here because of (<)
banner: "Running version ${version}"
```

Without `(<)`, the `${version}` in `banner` would fail because `version` is scoped to `settings.yaml`.

Another common use: sharing defines across multiple includes.

```yaml
<<(<): !include file:$DIR/constants.yaml

# all !define variables from constants.yaml are now in scope
output: "${project_name}/results"
```

## Optional includes with !include?

`!include?` (with the question mark) silently returns nothing if the file doesn't exist. No error, no warning.

```yaml
database:
  host: localhost
  port: 5432

# merge in local overrides if they exist
<<{<+}: !include? file:$DIR/local-overrides.yaml
```

Good for `.gitignore`d developer-specific tweaks, machine-specific paths, or optional feature configs.

## Complete pattern

Here's the full layering pattern for a multi-environment project:

```
config/
  base.yaml                 # shared defaults
  env/
    dev.yaml                # dev overrides
    prod.yaml               # prod overrides
    staging.yaml            # staging overrides
  local-overrides.yaml      # gitignored, per-developer tweaks
```

```yaml
# config/env/prod.yaml
!define environment: prod

check_interval: 15
log_level: WARN

database:
  host: db.prod.internal
  password: ${getenv('DB_PASSWORD')}

<<{>+}: !include file:$DIR/../base.yaml
<<{<+}: !include? file:$DIR/../local-overrides.yaml
```

```yaml
# config/base.yaml
!set_default environment: dev

sites:
  - https://example.com
  - https://status.example.com

check_interval: 60
log_level: INFO

database:
  host: localhost
  port: 5432
  name: myapp
  password: dev-pass
```

Loading `+config/env/prod.yaml` gives you: prod's overrides on top of base defaults, with optional local tweaks, and the database password pulled from the environment.

Check the result with:

```bash
dracon show config/env/prod.yaml -r
```
