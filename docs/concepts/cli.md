# Concepts: CLI Generation

Dracon's command-line interface (CLI) generation bridges the gap between configuration management and application execution, providing a powerful and type-safe way to interact with your application.

## The Core Idea: Model-Driven CLIs

Instead of manually writing argument parsing logic using libraries like `argparse` or `click`, Dracon generates the CLI directly from a Pydantic `BaseModel`.

### Using `@dracon_program` (Recommended)

The simplest way to create a CLI program:

```python
from dracon import dracon_program, Arg
from pydantic import BaseModel
from typing import Annotated

@dracon_program(name="my-app", description="My application")
class Config(BaseModel):
    environment: Annotated[str, Arg(short='e', help="Deployment env")]
    workers: int = 4

    def run(self):
        print(f"Running in {self.environment} with {self.workers} workers")

Config.cli()  # parses sys.argv, loads config, calls .run()
```

The decorator adds `.cli()`, `.invoke()`, `.from_config()`, and `.load()` methods to your model class. See the [CLI reference](../reference/cli_arg.md) for all decorator options.

### Using `make_program` (Low-Level)

For more control, use `make_program` directly:

1.  **Define Configuration:** Define your application's configuration parameters, their types, defaults, and help text using a Pydantic model.
2.  **Annotate for CLI:** Use `typing.Annotated` and `dracon.Arg` to customize how specific fields map to CLI arguments (e.g., short flags, positional arguments).
3.  **Generate Program:** Call `dracon.make_program(YourModel, ...)` to create a `Program` instance.
4.  **Parse Arguments:** Call `program.parse_args()` which handles:
    - Parsing standard CLI flags (`--option value`, `--option=value`, `-o val`) and positional arguments.
    - Generating a `--help` message automatically.
    - Handling special Dracon arguments:
      - `+config/file.yaml`: Loads and merges specified YAML configuration files.
      - `+config.yaml@sub.key`: Loads a file and extracts a subtree.
      - `++VAR=value` or `++VAR value`: Sets context variables for interpolation (shorthand for `--define.VAR=value`).
    - Applying overrides from the CLI onto the defaults and loaded files.
    - Validating the final configuration against your Pydantic model.
    - Returning the validated Pydantic model instance.

## Free Ordering

All argument types can be **freely mixed in any order** on the command line:

```bash
my-app action +base.yaml --workers 4 +overrides.yaml ++runname test -e prod
```

Dracon classifies each token by its prefix (`+`, `++`, `--`, `-`, or none) and processes them accordingly, regardless of position.

## Subcommands

Dracon supports subcommands (like `git remote add` or `docker compose up`) via Pydantic discriminated unions. The model defines the schema — no separate subcommand registration needed.

Each subcommand is a `BaseModel` with a discriminator field (`action: Literal['name'] = 'name'`), and the root model declares the subcommand field using `Subcommand(*types)`:

```python
from dracon import dracon_program, Arg, Subcommand
from pydantic import BaseModel
from typing import Annotated, Literal

class TrainCmd(BaseModel):
    """Train a model."""
    action: Literal['train'] = 'train'
    epochs: Annotated[int, Arg(help="Number of epochs")] = 10

    def run(self, ctx):
        print(f"Training for {self.epochs} epochs (verbose={ctx.verbose})")

class EvalCmd(BaseModel):
    """Evaluate a model."""
    action: Literal['eval'] = 'eval'
    dataset: Annotated[str, Arg(help="Test dataset path")]

    def run(self, ctx):
        print(f"Evaluating on {self.dataset}")

@dracon_program(name="ml-tool")
class CLI(BaseModel):
    verbose: Annotated[bool, Arg(short='v')] = False
    command: Subcommand(TrainCmd, EvalCmd)
```

Usage:

```bash
ml-tool train --epochs 50
ml-tool --verbose eval --dataset test.csv
ml-tool train --help                        # per-subcommand help
```

### Shared Options

Options defined on the root model (like `--verbose` above) can appear before or after the subcommand name — both are equivalent:

```bash
ml-tool --verbose train --epochs 50
ml-tool train --epochs 50 --verbose
```

### Config File Scoping

Config files (`+file`) are scoped by position relative to the subcommand name:

- **Before** the subcommand → merges at root level
- **After** the subcommand → merges under the subcommand field only

```bash
ml-tool +base.yaml train                    # root-scoped
ml-tool train +training.yaml                # subcommand-scoped (file just needs epochs/lr, no wrapper)
```

A full config file at root level can also specify the subcommand via the discriminator field:

```yaml
# full_config.yaml
verbose: true
command:
  action: train
  epochs: 50
```

### Run Dispatch

When using `@dracon_program`, `.cli()` dispatches `.run()` automatically:

1. If the **root model** has `.run()` → calls `instance.run()` (developer controls everything)
2. Else if the **subcommand** has `.run(ctx)` → calls `subcmd.run(root_instance)` with the root config as context
3. Else → returns the config instance

### Nested Subcommands

Subcommands can themselves contain `Subcommand` fields for multi-level nesting:

```bash
git-tool remote add --name origin
```

See the [CLI customization guide](../guides/customize-cli.md#subcommands) and [Subcommand reference](../reference/cli_arg.md#subcommands) for full details.

## Configuration Loading and Precedence

This is where Dracon's CLI integrates seamlessly with its configuration loading capabilities. When `program.parse_args()` runs, configuration sources are applied in a specific order, with later sources overriding earlier ones:

1.  **Pydantic Model Defaults:** Initial values defined in your `BaseModel` (`field: int = 10`).
2.  **`+file1.yaml`:** The first configuration file specified with `+` is loaded and composed (including its own includes, merges, etc.). Its values override the Pydantic defaults.
3.  **`+file2.yaml`:** The second `+` file is loaded and _merged onto the result_ of step 2 (using Dracon's default merge strategy `<<{<+}[<~]` unless customized globally, though CLI merging isn't typically customized).
4.  **... Subsequent `+fileN.yaml` files:** Each is merged sequentially.
5.  **`++VAR=value` Context:** Variables defined via `++` (or the longer form `--define.VAR=value`) are added to the context, potentially influencing subsequent interpolations within CLI argument values or during final resolution.
6.  **CLI Argument Overrides (`--key value`, positional args):** Values provided directly on the command line override any values from previous steps.

    - **Nested Keys:** Use dot notation (`--database.host db.prod`) to target nested fields within your Pydantic model. Dracon internally builds the necessary nested dictionary structure.
    - **File Values:** If an argument value starts with `+` (or the corresponding `Arg` has `is_file=True`), Dracon loads the referenced file/key path and uses its _content_ as the value for that specific CLI argument, merging it appropriately if the target field expects a mapping or sequence. Example: `--database +db_override.yaml` would load `db_override.yaml` and merge its content into the `database` field.

7.  **Pydantic Validation:** The final, merged dictionary representing the configuration is validated against your Pydantic model (`AppConfig.model_validate(...)`). This catches type errors, missing required fields, and runs custom validators.

## Argument Mapping

- **Field Names:** `my_field_name` becomes both `--my_field_name` and `--my-field-name` by default (auto dash aliasing). Customizable with `Arg(long=...)` or disabled per-field with `Arg(auto_dash_alias=False)`.
- **Types:** Pydantic types determine expected input (str, int, float, bool). `bool` fields become flags (`--verbose`, no value needed).
- **Equals Syntax:** All non-flag options support `--option=value` in addition to `--option value`.
- **Nested Models:** Fields that are Pydantic models allow nested overrides using dot notation (`--database.port 5433` or `--database.port=5433`). This works for _any_ nested key, even if the developer didn't define an explicit `Arg` for it. Dracon handles constructing the nested dictionary. If the nested argument itself is marked with `Arg(is_file=True)`, passing a file path will load that file's content _into_ that nested structure.

## Collection Argument Support

Dracon automatically detects and handles collection types (lists, tuples, sets, dictionaries) with user-friendly command-line syntaxes:

- **List-like arguments** (`List[T]`, `Tuple[T, ...]`, `Set[T]`) accept space-separated values: `--tags web api backend`
- **Dict-like arguments** (`Dict[K, V]`) accept key=value pairs: `--config debug=true port=8080`
- **Nested dictionaries** use dot notation: `--config app.name=myapp database.host=localhost`
- **Traditional syntax** is also supported: `--tags "['web', 'api']"` or `--config '{"debug": true}'`

When a positional argument is a collection type, it consumes all remaining non-option arguments, so only one collection positional argument is allowed per command.

This integration means your CLI automatically respects your defined configuration structure, types, defaults, and validation rules, while also benefiting from Dracon's powerful file loading, merging, and interpolation features.

## Debugging

- **`DRACON_SHOW_VARS=1`**: Set this environment variable to print a table of all defined variables (CLI `++` vars, config `!define` vars) and their sources when running a CLI program.
- **Unused variable warnings**: If a `++VAR` is defined but never referenced in any `${VAR}` expression, a warning is printed to help catch typos.
