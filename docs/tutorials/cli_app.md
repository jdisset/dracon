# Tutorial: Building a Configuration-Driven CLI App

!!! abstract
    We will build a simple, type-safe, automatically generated command-line application that can be configured via layered YAML files and command-line arguments and has strong type-safety.

## Step 1: Project Setup

Create a project directory with the following structure:

```
dracon_tutorial/
├── config/
│   ├── base.yaml
│   ├── prod.yaml
│   └── db_user.secret
├── models.py
└── main.py
```

## Step 2: Define Configuration Models (`models.py`)

We use Pydantic models to define the structure and types of our configuration. Dracon uses these models for validation and CLI argument generation.

```python title="models.py"
--8<-- "examples/models.py"
```

- `DatabaseConfig`: Defines database connection details with defaults.
- `AppConfig`: Defines the main application settings.
  - `Annotated` and `dracon.Arg` are used to customize CLI arguments (short flags `-e`, help text, marking `environment` as required).
  - `database` uses `Field(default_factory=...)` for the nested Pydantic model.
  - `output_path` is marked as `DeferredNode[str]`. This tells Dracon its final value depends on runtime context and construction should be delayed until `dracon.construct()` is called.
- `process_data`: An example method showing how to use the configuration, including constructing the deferred `output_path`.
- `generate_unique_id`: A helper simulating runtime value generation.

## Step 3: Create Base Configuration (`config/base.yaml`)

This file defines default settings and can load sensitive data from other sources.

```yaml title="config/base.yaml"
--8<-- "examples/config/base.yaml"
```

- `log_level`: Uses lazy interpolation (`${...}`) to read the `LOG_LEVEL` environment variable, falling back to `"INFO"`.
- `database.host`: Uses a cross-reference (`@/environment`) to dynamically build the host based on the final `environment` value after all merging/overrides.
- `database.username`: Uses `!include file:$DIR/...` to load the username from `db_user.secret` located in the same directory (`$DIR`).
- `database.password`: Uses `!include env:DB_PASS` to load the password directly from the `DB_PASS` environment variable during the composition phase.
- `output_path`: Defines the structure, but `${computed_runtime_value}` needs to be provided later via `construct()`.

## Step 4: Create Production Overrides (`config/prod.yaml`)

This file overrides specific settings for the production environment and merges the base configuration.

```yaml title="config/prod.yaml"
--8<-- "examples/config/prod.yaml"
```

- It explicitly sets `environment`, `log_level`, `workers`, `database.host`, and `database.username`.
- The `<<{<+}: !include file:base.yaml` line is crucial:
  - `<<:` indicates a merge operation.
  - `!include file:base.yaml` specifies the source to merge (our base config).
  - `{<+}` defines the merge strategy: recursively merge dictionaries (`+`), letting values from the _new_ source (base.yaml in this case) win conflicts (`<`). This means defaults from `base.yaml` will be used if not defined in `prod.yaml`. If we wanted `prod.yaml` values to always take precedence, we would use `{>+}`.

## Step 5: Create Secret File (`config/db_user.secret`)

A simple text file holding the base database username.

```text title="config/db_user.secret"
base_user
```

## Step 6: Create the CLI Script (`main.py`)

This script uses Dracon to create the CLI program based on `AppConfig`.

```python title="main.py"
--8<-- "examples/main.py"
```

- `make_program(AppConfig, ...)`: This is the core of CLI generation. Dracon inspects `AppConfig` and the `Arg` annotations.
- `context={...}`: We pass the Pydantic models to the loader's context so Dracon knows how to construct `!AppConfig` or `!DatabaseConfig` tags if encountered in YAML (though not strictly needed in this specific example's YAML, it's good practice).
- `program.parse_args(sys.argv[1:])`: This function does the heavy lifting:
  - Parses standard CLI arguments (`-e`, `--workers`, etc.).
  - Detects configuration files prefixed with `+` (e.g., `+config/prod.yaml`).
  - Loads and merges the base Pydantic defaults, the specified config files (in order), and CLI overrides according to Dracon's precedence rules.
  - Handles `--define.VAR=value` arguments.
  - Validates the final configuration object against `AppConfig`.
  - Returns the validated `AppConfig` instance (`cli_config`).
- `cli_config.process_data()`: We call our application logic using the fully configured object.

## Step 7: Run the Application

Now, let's run it with different configurations:

1.  **Show Help:** See the automatically generated help message.

    ```bash
    python main.py --help
    ```

    _(You should see output similar to the screenshot in the Introduction)_

2.  **Run with Development Environment:** Requires the `DB_PASS` environment variable.

    ```bash
    export DB_PASS="dev_secret_shhh"
    python main.py +config/base.yaml -e dev
    ```

    _Expected Output Snippets:_

    ```text
    Processing for environment: dev
    Using Database:
      Host: db.dev.local
      User: base_user
    Settings:
      Workers: 1
      Log Level: INFO
    Constructing output path...
      Output Path: /data/outputs/dev-db.dev.local-1-xxxxxxxxx
    ```

!!! note
    The host is `db.dev.local` because `environment` became 'dev'. The timestamp in the output path will vary.)

3.  **Run with Production Config & Overrides:** Load `prod.yaml` and override `workers`. Also set `LOG_LEVEL` via environment.

    ```bash
    export LOG_LEVEL=DEBUG
    export DB_PASS="prod_secret_much_safer"
    python main.py +config/prod.yaml --workers 8
    ```

    _Expected Output Snippets:_

    ```text
    Processing for environment: production
    Using Database:
      Host: db.prod.svc.cluster.local
      User: prod_db_user
    Settings:
      Workers: 8
      Log Level: DEBUG
    Constructing output path...
      Output Path: /data/prod/production-db.prod.svc.cluster.local-8-xxxxxxxxx
    ```

!!! note
    `environment`, `host`, `user`, and initial `workers` came from `prod.yaml`. `log_level` came from the environment variable. `workers=8` came from the CLI override. The output path format is also from `prod.yaml`.)

4.  **Override Nested Value from File:**
    ```bash
    echo "cli_override_user" > /tmp/override_user.secret
    python main.py +config/prod.yaml --database.username +/tmp/override_user.secret
    ```
    _(Expected: The database username will be `cli_override_user`)_
