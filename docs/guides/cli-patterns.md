# CLI Patterns

You want a CLI that goes beyond basic flags. Subcommands, auto-discovered config files, file arguments, custom actions, programmatic config factories.

## Subcommands with discriminated unions

Use this when your tool has distinct modes (train/eval, deploy/rollback, etc.) each with their own options.

### Define subcommand models

Each subcommand is a Pydantic model with a `Literal` discriminator field:

```python
from typing import Literal, Annotated
from pydantic import BaseModel
from dracon import Arg, Subcommand, dracon_program

class TrainCmd(BaseModel):
    """Train a model."""
    action: Literal['train'] = 'train'
    epochs: Annotated[int, Arg(help="Number of epochs")] = 10
    lr: Annotated[float, Arg(help="Learning rate")] = 0.001

    def run(self, ctx):
        print(f"Training for {self.epochs} epochs, lr={self.lr}")
        print(f"Verbose: {ctx.verbose}")

class EvalCmd(BaseModel):
    """Evaluate a model on test data."""
    action: Literal['eval'] = 'eval'
    dataset: Annotated[str, Arg(help="Test dataset path")] = "test.csv"

    def run(self, ctx):
        print(f"Evaluating on {self.dataset}")
```

### Wire them into the root model

```python
@dracon_program(name="ml")
class MLConfig(BaseModel):
    verbose: Annotated[bool, Arg(short="v", help="Verbose output")] = False
    command: Subcommand(TrainCmd, EvalCmd)

if __name__ == "__main__":
    MLConfig.cli()
```

`Subcommand(TrainCmd, EvalCmd)` creates an `Annotated[Union[TrainCmd, EvalCmd], ...]` with the right discriminator and `Arg(subcommand=True, positional=True)` metadata. The discriminator field defaults to `action`; pass `discriminator="cmd"` to change it.

### Less boilerplate with @subcommand

The `@subcommand` decorator injects the discriminator field for you:

```python
from dracon import subcommand

@subcommand("train")
class TrainCmd(BaseModel):
    """Train a model."""
    epochs: Annotated[int, Arg(help="Number of epochs")] = 10

@subcommand("eval")
class EvalCmd(BaseModel):
    """Evaluate a model on test data."""
    dataset: Annotated[str, Arg(help="Test dataset path")] = "test.csv"
```

No need to write `action: Literal['train'] = 'train'` yourself.

### Running it

```bash
ml train --epochs 50 --lr 0.01
ml eval --dataset validation.csv
ml --verbose train --epochs 5
```

The subcommand's `.run(ctx)` method receives the parent config as `ctx`, so it can access shared options like `verbose`.

### Config file scoping

Config files placed before the subcommand name merge into the root config. Files after merge into the subcommand:

```bash
ml +global.yaml train +train-config.yaml --epochs 20
```

Here, `global.yaml` is root-scoped (can set `verbose`, etc.) and `train-config.yaml` is scoped to the `train` subcommand.

### Per-subcommand help

```bash
ml --help           # shows commands list
ml train --help     # shows train-specific options
```

The docstring on each subcommand model appears as the command description.

## Layered configs as CLI plug-ins

Use this when you want a layered config file to *grow* the flag set of your
CLI. Top-level `!require` and `!set_default` directives in a `+file.yaml`
become real argparse flags — `--help`-visible, with optional short alias.

A small CLI:

```python
from typing import Annotated
from pydantic import BaseModel
from dracon import Arg, dracon_program

@dracon_program(name="mycli")
class Config(BaseModel):
    name: Annotated[str, Arg(help="report name")] = "anon"
```

A plugin layer that declares its own knobs:

```yaml
# plugins/analytics.yaml
!require api_key:
  help: "API key for the analytics service"

!set_default:int batch_size:
  default: 32
  help: "batch size"
  short: -b

# the plugin uses what it declared
analytics:
  endpoint: https://api.example.com/${api_key}
  batch:    ${batch_size}
```

A plain user invocation:

```bash
mycli +plugins/analytics.yaml --api-key $SECRET -b 64
```

`--help` shows `--api-key` and `--batch-size` with their hint text. The
plugin file *is* the flag declaration; no Python edit was needed to add
those flags.

A few things to keep in mind:

- The directive must be at the **top level** of the layered file. Directives
  inside `!fn` / `!deferred` / `!if` are inner-scope contracts, not CLI flags.
- A model field with the same name shadows a YAML directive. `++port=8080`
  still targets the YAML variable when you need to disambiguate.
- Short aliases (`short: -b`) are best-effort: if `-b` is already taken by
  a model-side `Arg`, the long flag still works and a one-shot warning is
  emitted.
- `!set_default:int` wires `int` as the argparse `type=`, so `--batch-size 64`
  produces an int, not a string.

For the precedence rules and the `++` fallback, see
[CLI flags from config layers](../reference/cli-api.md#cli-flags-from-config-layers).

## ConfigFile for auto-discovered configs

Use this when you want your tool to automatically pick up config files from known locations.

```python
from dracon import dracon_program, ConfigFile

@dracon_program(
    name="deploy",
    config_files=[
        ConfigFile("~/.deploy/config.yaml"),
        ConfigFile(".deploy.yaml", search_parents=True),
    ],
)
class DeployConfig(BaseModel):
    target: str = "staging"
    replicas: int = 1
```

- `~/.deploy/config.yaml` is checked once (expanded with `~`). If it exists, it's loaded.
- `.deploy.yaml` with `search_parents=True` uses the cascade loader: walks up from CWD, collects all `.deploy.yaml` files, merges them root-first (closest wins).

The precedence order:

```
model defaults  <  auto-discovered configs  <  +file CLI args  <  --flag overrides
```

So a user can always override auto-discovered values with explicit `+file` or `--flag` arguments.

### Real-world pattern

A tool with home-dir defaults and project-local config:

```yaml
# ~/.deploy/config.yaml
target: production
replicas: 3
registry: registry.internal.com
```

```yaml
# /repo/services/api/.deploy.yaml
replicas: 5
```

Running `deploy` from `/repo/services/api/` automatically loads the home-dir config, then overlays the project-local one. No `+file` arguments needed.

## File arguments (is_file=True)

Use this when a CLI argument should load a YAML file as config instead of being treated as a string.

```python
@dracon_program(name="predict")
class PredictConfig(BaseModel):
    model_config_file: Annotated[
        ModelConfig,
        Arg(is_file=True, help="Path to model config YAML"),
    ]
    input: str = "data.csv"
```

```bash
predict --model-config-file model.yaml
```

The value of `--model-config-file` is loaded as YAML and validated against `ModelConfig`. It's not just a file path string.

You can combine this with a selector:

```bash
predict --model-config-file models.yaml@encoder
```

This extracts the `encoder` subtree from `models.yaml` and validates it.

## Action callbacks

Use this when you want a flag to trigger a side effect (like exporting the config and exiting).

```python
def export_json(program, config):
    import json
    print(json.dumps(config, indent=2, default=str))
    raise SystemExit(0)

@dracon_program(name="myapp")
class MyConfig(BaseModel):
    port: int = 8080
    export: Annotated[
        bool,
        Arg(action=export_json, help="Export config as JSON and exit"),
    ] = False
```

```bash
myapp +config.yaml --export
```

The `action` callback receives the `Program` instance and the parsed config dict. It runs after parsing but before model validation.

## Raw arguments (raw=True)

Use this when a field should receive its value as-is, without YAML parsing or interpolation.

```python
@dracon_program(name="runner")
class RunnerConfig(BaseModel):
    command: Annotated[
        str,
        Arg(positional=True, raw=True, help="Shell command to run"),
    ]
```

```bash
runner "echo \${HOME}"
```

Without `raw=True`, the `${HOME}` would be treated as a Dracon interpolation. With it, the string is passed through untouched.

Good for JSON strings, shell commands, regex patterns, or anything that might clash with Dracon's `${...}` syntax.

## make_callable() for config factories

Use this when you want to turn a YAML config into a reusable Python callable. Good for creating objects from config templates programmatically.

```python
from dracon import make_callable

create_model = make_callable("model.yaml", context_types=[ModelConfig])
```

```yaml
# model.yaml
!set_default layers: 3
!set_default lr: 0.001

!ModelConfig
architecture: transformer
layers: ${layers}
learning_rate: ${lr}
```

```python
# each call constructs a fresh config
small = create_model(layers=2, lr=0.01)
large = create_model(layers=12, lr=0.0001)
```

The YAML file is loaded once (as a deferred template). Each call to the returned function injects the kwargs as context and constructs a fresh result.

You can also build a callable from an existing `DeferredNode`:

```python
from dracon import DraconLoader, make_callable

loader = DraconLoader(deferred_paths=['/'])
node = loader.load("model.yaml")
create_model = make_callable(node)
```

Options:

- `context_types=[MyType]` makes types available for `!MyType` tags
- `context={'key': value}` provides base context (overridden by call-time kwargs)
- `auto_context=True` captures types from the caller's namespace

## Python API: .invoke(), .from_config(), .load()

The `@dracon_program` decorator adds several class methods beyond `.cli()`:

### .invoke(*configs, **context)

Load config files, validate, and run. Returns whatever `.run()` returns:

```python
result = MLConfig.invoke("config.yaml", env="prod")
```

The positional args are config file paths (automatically prefixed with `+` if needed). The keyword args are injected as context variables.

### .from_config(*configs, **context)

Same as `.invoke()` but skips the `.run()` call. Returns the validated model instance:

```python
config = MLConfig.from_config("config.yaml", env="prod")
print(config.verbose)
```

Good for tests, or when you need the config object without executing the program.

### .load(path, context=None)

Low-level: loads a single file through the Dracon loader and validates against the model:

```python
config = MLConfig.load("config.yaml", context={"env": "prod"})
```

This bypasses the CLI argument parsing entirely. No `+file` merging, no auto-discovered configs.
