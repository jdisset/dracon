# Command-Line Interfaces

Dracon allows you to automatically generate command-line interfaces (CLIs) directly from your Pydantic configuration models. You can define your application's parameters and configuration structure in one place (the Pydantic model) and get a type-safe, well-documented CLI with integrated configuration file loading and overrides.

## Basic Usage

1.  **Define Your Configuration Model:** Use a Pydantic `BaseModel`.
2.  **(Optional) Annotate Fields:** Use `typing.Annotated` and `dracon.Arg` to customize CLI arguments (help text, short names, etc.).
3.  **Create the Program:** Use `dracon.make_program()`.
4.  **Parse Arguments:** Call `program.parse_args()`.

```python
# main.py
import sys
from pydantic import BaseModel
from typing import Annotated
from dracon import DraconLoader, make_program, Arg # Import necessary parts

# 1. Define the model
class CliConfig(BaseModel):
    input_file: Annotated[str, Arg(
        positional=True, # Make this a positional argument
        help="Path to the input data file."
    )]
    output_dir: Annotated[str, Arg(
        short='o', # Add a short flag -o
        help="Directory to save results."
    )]
    threshold: Annotated[float, Arg(help="Processing threshold.")] = 0.5 # Add default
    verbose: Annotated[bool, Arg(short='v', help="Enable verbose output.")] = False

    # Example application logic method
    def run(self):
        print(f"Running with config:")
        print(f"  Input: {self.input_file}")
        print(f"  Output Dir: {self.output_dir}")
        print(f"  Threshold: {self.threshold}")
        print(f"  Verbose: {self.verbose}")
        # ... your actual logic here ...

# 3. Create the program instance
program = make_program(
    CliConfig,
    name="my-data-processor", # Optional: Program name for help message
    description="Processes data files based on configuration." # Optional help description
)

if __name__ == "__main__":
    try:
        # 4. Parse arguments
        # Returns the populated Pydantic model instance and the raw args dict
        config_model, raw_args = program.parse_args(sys.argv[1:])

        # 5. Use the populated and validated model
        config_model.run()

    except Exception as e: # Catch potential parsing/validation errors
        print(f"Error: {e}", file=sys.stderr)
        # Consider calling program.print_help() here or letting it exit
        sys.exit(1)
```

## Running the CLI

The generated CLI supports several features automatically:

- **Help Message:**
  ```bash
  $ python main.py --help
  # Output: (Formatted help message based on model and Arg annotations)
  # Usage: my-data-processor [OPTIONS] INPUT_FILE
  #
  # Arguments:
  #   INPUT_FILE    Path to the input data file.
  #                 type: STR
  #                 REQUIRED
  # ... etc ...
  ```
- **Positional Arguments:**
  ```bash
  $ python main.py path/to/data.csv --output-dir results/
  # input_file='path/to/data.csv', output_dir='results/', threshold=0.5, verbose=false
  ```
- **Optional Arguments (Long/Short):**

  ```bash
  $ python main.py data.csv -o out/ --threshold 0.8 -v
  # input_file='data.csv', output_dir='out/', threshold=0.8, verbose=true
  ```

  !!! note
  Option names are automatically derived from field names (e.g., `output_dir` -> `--output-dir`). Use `Arg(long='custom-name')` to override.

- **Boolean Flags:** Fields typed as `bool` become flags. Simply including the flag sets it to `True`.
  ```bash
  $ python main.py data.csv -o out # verbose is false (default)
  $ python main.py data.csv -o out -v # verbose is true
  ```

## Customizing Arguments with `Arg`

The `dracon.Arg` class, used within `Annotated`, provides fine-grained control:

```python
from typing import Annotated
from dracon import Arg

class AdvancedConfig(BaseModel):
    config_file: Annotated[str, Arg(
        long='config', # Custom long name (--config instead of --config-file)
        short='c',
        help='Path to primary configuration YAML file.'
    )]
    threads: Annotated[int, Arg(
        help='Number of processing threads (0 for auto).',
        default=1 # Override Pydantic default for CLI help if needed
    )]
    input_path: Annotated[str, Arg(
        positional=True, # A positional argument
        help='Input data source.'
    )]
    force_update: Annotated[bool, Arg(
        short='f',
        help='Force update even if output exists.'
    )]
    log_setup_level: Annotated[str, Arg(
        # Execute this function when the arg is parsed
        action=setup_logging_action, # Define this function elsewhere
        help='Set logging level (DEBUG, INFO, etc).'
    )]
    output_path: Annotated[Resolvable[str], Arg(
        # Mark as resolvable for post-processing
        resolvable=True,
        help='Output file path (can be derived).'
    )]
    metadata_file: Annotated[str, Arg(
         # Automatically treat value as 'file:...' for Dracon includes/loading
        is_file=True,
        help='Path to metadata YAML file.'
    )]
```

- `short`: Single character for the short flag (e.g., `'c'` for `-c`).
- `long`: Custom long flag name (e.g., `'config'` for `--config`).
- `help`: Description shown in `--help`.
- `positional`: If `True`, the argument is positional instead of an option flag. Order is determined by field definition order in the model.
- `action`: A function `func(program: Program, value: Any)` called immediately after the argument value is parsed. Useful for side effects like setting up logging.
- `resolvable`: If `True`, the argument's value will be wrapped in a `Resolvable` object, delaying its final processing (see [Resolvable Values](resolvable.md)).
- `is_file`: If `True`, instructs Dracon internally that this argument represents a file path, potentially influencing how it's handled if used within Dracon's loading/include mechanisms activated by CLI arguments.
- `default`: Can be used to specify a default value specifically for the CLI help message, potentially overriding the Pydantic model default for display purposes.

## Integration with Dracon Configuration Loading

This is where the CLI module truly integrates with the rest of Dracon:

1.  **Loading Config Files (`+` prefix):** Arguments starting with `+` are treated as configuration files to be loaded and merged _before_ applying CLI overrides.

    ```bash
    # Load base config, then production overrides, then apply CLI args
    $ python main.py +base.yaml +prod.yaml path/to/data.csv --threshold 0.9
    ```

    Files are merged sequentially using Dracon's default merge strategy (`{~<}[~<]` - roughly, replace keys/lists, new wins).

2.  **CLI Overrides (`--key value`):** Standard option arguments directly override values coming from defaults or loaded config files. Nested keys are supported using dot notation.

    ```bash
    # Assume config.yaml defines database.host = 'localhost'
    $ python main.py +config.yaml data.csv --database.host db.prod.svc --database.port 5433
    ```

3.  **Defining Context Variables (`--define.`):** You can set context variables for Dracon's interpolation engine directly from the CLI.
    ```bash
    # Define context variables ENV and BATCH_SIZE
    $ python main.py data.csv --define.ENV=production --define.BATCH_SIZE=100
    ```
    These variables (`ENV`, `BATCH_SIZE`) become available within `${...}` expressions in your loaded YAML files.

## Order of Precedence

Dracon applies configuration sources in the following order (later sources override earlier ones):

1.  Pydantic Model Defaults.
2.  First `+config1.yaml` loaded.
3.  Second `+config2.yaml` loaded (merged onto result of #2).
4.  ... subsequent `+configN.yaml` files.
5.  Context variables from `--define.VAR=value`.
6.  CLI argument overrides (`--key value`).

Dracon's merging, includes, and interpolation rules are applied throughout this process.

## Putting It Together

The `commandline` module provides a seamless way to build robust, type-safe CLIs that fully integrate with Dracon's powerful configuration loading capabilities, allowing users to configure your application through a combination of defaults, files, environment variables (via YAML), and command-line arguments.
