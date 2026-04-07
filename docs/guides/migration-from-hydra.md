# Migration from Hydra

You've been using Hydra+OmegaConf and want to try Dracon. Here's the concept mapping and some translated patterns.

## Concept mapping

| Hydra / OmegaConf | Dracon | Notes |
|---|---|---|
| Defaults list | `!include` + `<<:` merge keys | Explicit, visible in the YAML |
| Config groups (directories) | `!include file:${var}.yaml` | Dynamic includes with interpolation |
| `@package` directive | `<<@path:` merge at a keypath | Merge-at-path syntax |
| `_target_: my.module.Class` | `!my.module.Class` | Tag-based construction; no magic keys |
| `_recursive_: true/false` | Always recursive (natural) | Dracon constructs nested types naturally |
| `_partial_: true` | `!deferred` or `!fn:path` | `!deferred` pauses construction; `!fn:path` creates a callable partial |
| `${path.to.node}` | `${@/path.to.node}` | `@/` for absolute paths, `@.` for relative |
| `oc.register_new_resolver` | Any callable in loader context | Pass functions via `context={}` |
| Structured configs (dataclasses) | Pydantic models | Full validation, type coercion, defaults |
| `key=value` CLI overrides | `--key value` CLI | Standard CLI flags, auto-generated from model |
| `++key=value` (force add) | `++key=value` (context variable) | In Dracon, `++` sets context vars for `${...}` |
| `--multirun` | `!each` | `!each` is a composition-time loop |

## Pattern translations

### 1. Defaults list to !include + merge

**Hydra:**
```yaml
defaults:
  - db: postgres
  - server: apache
  - _self_

db:
  timeout: 30
```

**Dracon:**
```yaml
<<{>+}: !include file:$DIR/db/postgres.yaml
<<{>+}: !include file:$DIR/server/apache.yaml

db:
  timeout: 30
```

The merge key `<<{>+}` means "merge recursively, my values (the current file) win conflicts." Files are layered explicitly. The `_self_` concept doesn't exist because ordering is explicit: your local keys are always defined in place, and merges happen where you write them.

Alternatively, use the CLI layering:

```bash
myapp +db/postgres.yaml +server/apache.yaml +config.yaml
```

### 2. Config group selection to dynamic include

**Hydra:**
```yaml
defaults:
  - db: ${db_type}
```

**Dracon:**
```yaml
<<{>+}: !include file:$DIR/db/${db_type}.yaml
```

The `${db_type}` is resolved during composition. Pass it as a context variable:

```bash
myapp +config.yaml ++db_type=postgres
```

Or define it in the config itself:

```yaml
!define db_type: postgres

<<{>+}: !include file:$DIR/db/${db_type}.yaml
```

### 3. Object instantiation to type tags

**Hydra:**
```yaml
optimizer:
  _target_: torch.optim.Adam
  lr: 0.001
  weight_decay: 1e-5
```

**Dracon:**
```yaml
optimizer: !torch.optim.Adam
  lr: 0.001
  weight_decay: 1e-5
```

The tag `!torch.optim.Adam` tells Dracon to import `torch.optim.Adam` and construct it with the mapping as kwargs. No `_target_` indirection.

For Pydantic models, the tag works the same way:

```yaml
model: !mypackage.MyModel
  name: "experiment-1"
  layers: 12
```

### 4. Sweep to !each

**Hydra multirun:**
```bash
python train.py -m optimizer.lr=0.001,0.01,0.1
```

**Dracon !each:**
```yaml
!define learning_rates: [0.001, 0.01, 0.1]

configs:
  !each(lr) ${learning_rates}:
    - optimizer: !torch.optim.Adam
        lr: ${lr}
```

`!each` generates one config per item during composition. You can inspect the result with `dracon show`.

For grid sweeps, nest `!each`:

```yaml
!define lrs: [0.001, 0.01]
!define wds: [0.0, 1e-5]

configs:
  !each(lr) ${lrs}:
    !each(wd) ${wds}:
      - optimizer: !torch.optim.Adam
          lr: ${lr}
          weight_decay: ${wd}
```

## What Dracon has that Hydra doesn't

- **`!if` / `!each`**: conditional and iterative config generation at composition time
- **`!fn`**: define YAML functions (parameterized templates) that can be called from `${...}` expressions
- **`!pipe`**: chain functions together
- **Expression engine**: full Python expressions in `${...}`, not just variable references
- **Merge grammar**: fine-grained control over how dicts and lists merge (`{<+}`, `{>+}`, `[<~]`, `[>+]`, etc.)
- **Permissive evaluation**: resolve what you can, leave the rest as strings
- **CompositionStack**: programmatic multi-layer composition with per-layer merge strategies
- **Provenance tracing**: `--trace db.port` shows the full history of how a value got its final state
- **`!assert`**: runtime assertions in your config files
- **`!require`**: declare mandatory context variables with helpful error messages

## What Hydra has that Dracon doesn't

- **Automatic output directories**: Hydra creates timestamped output dirs. In Dracon, set `output_dir: "${now()}/"` or handle it in your application code.
- **`~key` deletion**: Hydra lets you delete keys with the tilde prefix. Dracon uses `!unset` or merge strategies instead.
- **Bayesian sweepers / Ax integration**: Hydra has plugins for Bayesian optimization. For Dracon, use [Broodmon](https://github.com/weiss/broodmon) for experiment management and sweeps.
- **Tab completion for config groups**: Hydra auto-completes config group names. Dracon's CLI completions are model-aware but don't know about arbitrary config files.

## Further reading

The mental models are different enough that a 1:1 translation isn't always the right approach. Dracon leans into explicit composition over convention, and type tags over magic keys. If something feels awkward to translate, there's probably a more natural way to express it in Dracon. Check the [config layering guide](config-layering.md) and [YAML functions guide](yaml-functions.md) for patterns that don't have direct Hydra equivalents.
