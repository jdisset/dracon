# Concepts: CLI Generation

Dracon's command-line interface (CLI) generation bridges the gap between configuration management and application execution, providing a powerful and type-safe way to interact with your application.

## The Core Idea: Model-Driven CLIs

Instead of manually writing argument parsing logic using libraries like `argparse` or `click`, Dracon generates the CLI directly from a Pydantic `BaseModel`.

1.  **Define Configuration:** You define your application's configuration parameters, their types, defaults, and help text using a Pydantic model.
2.  **Annotate for CLI:** You use `typing.Annotated` and `dracon.Arg` to customize how specific fields map to CLI arguments (e.g., short flags, positional arguments).
3.  **Generate Program:** You call `dracon.make_program(YourModel, ...)` to create a `Program` instance.
4.  **Parse Arguments:** You call `program.parse_args()` which handles:
    - Parsing standard CLI flags (`--option value`, `-o val`) and positional arguments.
    - Generating a `--help` message automatically.
    - Handling special Dracon arguments:
      - `+config/file.yaml`: Loads and merges specified YAML configuration files.
      - `--define.VAR=value`: Sets context variables for interpolation.
    - Applying overrides from the CLI onto the defaults and loaded files.
    - Validating the final configuration against your Pydantic model.
    - Returning the validated Pydantic model instance.

## Configuration Loading and Precedence

This is where Dracon's CLI integrates seamlessly with its configuration loading capabilities. When `program.parse_args()` runs, configuration sources are applied in a specific order, with later sources overriding earlier ones:

1.  **Pydantic Model Defaults:** Initial values defined in your `BaseModel` (`field: int = 10`).
2.  **`+file1.yaml`:** The first configuration file specified with `+` is loaded and composed (including its own includes, merges, etc.). Its values override the Pydantic defaults.
3.  **`+file2.yaml`:** The second `+` file is loaded and _merged onto the result_ of step 2 (using Dracon's default merge strategy `<<{<+}[<~]` unless customized globally, though CLI merging isn't typically customized).
4.  **... Subsequent `+fileN.yaml` files:** Each is merged sequentially.
5.  **`--define.VAR=value` Context:** Variables defined via `--define.` are added to the context, potentially influencing subsequent interpolations within CLI argument values or during final resolution.
6.  **CLI Argument Overrides (`--key value`, positional args):** Values provided directly on the command line override any values from previous steps.

    - **Nested Keys:** Use dot notation (`--database.host db.prod`) to target nested fields within your Pydantic model. Dracon internally builds the necessary nested dictionary structure.
    - **File Values:** If an argument value starts with `+` (or the corresponding `Arg` has `is_file=True`), Dracon loads the referenced file/key path and uses its _content_ as the value for that specific CLI argument, merging it appropriately if the target field expects a mapping or sequence. Example: `--database +db_override.yaml` would load `db_override.yaml` and merge its content into the `database` field.

7.  **Pydantic Validation:** The final, merged dictionary representing the configuration is validated against your Pydantic model (`AppConfig.model_validate(...)`). This catches type errors, missing required fields, and runs custom validators.

## Argument Mapping

- **Field Names:** `my_field_name` becomes `--my-field-name` by default (can be customized with `Arg(long=...)`).
- **Types:** Pydantic types determine expected input (str, int, float, bool). `bool` fields typically become flags (`--verbose`).
- **Nested Models:** Fields that are Pydantic models allow nested overrides using dot notation (`--database.port 5433`). Dracon handles constructing the nested dictionary. If the nested argument itself is marked with `Arg(is_file=True)`, passing a file path will load that file's content _into_ that nested structure.

This integration means your CLI automatically respects your defined configuration structure, types, defaults, and validation rules, while also benefiting from Dracon's powerful file loading, merging, and interpolation features.
