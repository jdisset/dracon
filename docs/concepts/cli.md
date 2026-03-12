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
