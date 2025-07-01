import sys
import os
from dracon import make_program

# Ensure models.py is in the same directory or Python path
from models import AppConfig, DatabaseConfig

# Create the CLI program from the Pydantic model
# Dracon automatically generates args for 'environment', 'log_level', 'workers', etc.
# It also handles nested fields like 'database.host', creating --database.host
program = make_program(
    AppConfig,  # The Pydantic model defining the configuration and CLI args
    name="my-cool-app",
    description="My cool application using Dracon for config and CLI.",
    # Provide models to Dracon's context so it can construct them
    # when encountering tags like !AppConfig or !DatabaseConfig in YAML files.
    context={
        'AppConfig': AppConfig,
        'DatabaseConfig': DatabaseConfig,
        # You can add other functions or variables here to make them
        # available inside ${...} expressions in your YAML files.
        # 'my_helper_func': some_function,
    },
)

if __name__ == "__main__":
    # Ensure the 'config' directory is accessible relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)  # Change CWD to script dir for relative paths

    print()
    print()
    print()
    # program.parse_args handles:
    # 1. Parsing known arguments based on AppConfig and Arg annotations.
    # 2. Identifying config files specified with '+' (e.g., +config/prod.yaml).
    # 3. Loading and merging these config files sequentially.
    # 4. Applying direct CLI overrides (e.g., --workers 8).
    # 5. Handling ++VAR=value (or --define.VAR=value) for context variables.
    # 6. Validating the final merged configuration against AppConfig.
    # 7. Returning the validated AppConfig instance and a dict of raw args.
    cli_config, raw_args = program.parse_args(sys.argv[1:])

    print("\n--- Successfully Parsed Config ---")
    # cli_config is now a fully populated and validated AppConfig instance
    # ready to be used by the application.
    cli_config.process_data()

    print("\n--- Raw Arguments Provided ---")
    print(raw_args)  # Shows the arguments as parsed by the CLI layer

