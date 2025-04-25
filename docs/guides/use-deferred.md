# How-To: Use Deferred Execution

Dracon allows you to delay parts of the configuration processing using `DeferredNode` and `Resolvable`.

## Delaying Node Construction (`DeferredNode`)

Use `!deferred` or `DraconLoader(deferred_paths=...)` when you need to postpone the _entire construction_ of a configuration branch, usually because required context (variables, functions) is only available later at runtime.

**Scenario:** Constructing a database connection string that requires a password fetched _after_ initial config loading.

**1. Mark the Node:**

```yaml
# config.yaml
database_config: !deferred:DatabaseConfig # Defer construction of DatabaseConfig
  host: db.example.com
  port: 5432
  username: app_user
  # Password needs runtime context
  connection_string: "postgresql://${username}:${DB_PASSWORD}@${host}:${port}/mydb"
# Define the Pydantic model (in Python)
# from pydantic import BaseModel
# class DatabaseConfig(BaseModel): ... host, port, username, connection_string ...
```

**2. Load Configuration:**

```python
# main.py
import dracon as dr
from models import DatabaseConfig # Your Pydantic model

loader = dr.DraconLoader(context={'DatabaseConfig': DatabaseConfig})
config = loader.load("config.yaml")

# config.database_config is a DeferredNode instance here
print(type(config.database_config)) # <class 'dracon.deferred.DeferredNode'>
```

**3. Provide Context and Construct:**

```python
# ... later in your code ...

# Fetch the password (e.g., from a secrets manager)
db_password = get_secret("database_password")

# Provide the missing context and call .construct()
runtime_context = {'DB_PASSWORD': db_password}
final_db_config = config.database_config.construct(context=runtime_context)

# Now final_db_config is the fully constructed DatabaseConfig instance
assert isinstance(final_db_config, DatabaseConfig)
print(final_db_config.connection_string)
# Output: postgresql://app_user:runtime_secret@db.example.com:5432/mydb

# Optionally, replace the deferred node in the main config
config.database_config = final_db_config
```

**Key Points for `DeferredNode`:**

- Pauses construction of the _entire tagged node_ and its children.
- Captures the YAML node structure and the context available _at load time_.
- Requires calling `.construct()` manually, providing any missing context.
- Useful for late-binding, resource initialization, or conditional construction.
- Can be targeted implicitly using `DraconLoader(deferred_paths=['/path/to/defer'])`.
- Use `!deferred::clear_ctx=VAR` or `!deferred::clear_ctx` to control context inheritance.

## Delaying Value Resolution (`Resolvable`)

Use `Resolvable[T]` (typically via type hints and `Arg(resolvable=True)`) when the configuration is _mostly_ loaded, but you need a final step to process or validate a _single specific value_, often after CLI parsing.

**Scenario:** A CLI argument for an output file path needs formatting based on another input argument.

**1. Define Model with `Resolvable` and `Arg`:**

```python
# models.py
from pydantic import BaseModel
from typing import Annotated
from dracon import Arg, Resolvable

class ProcessingConfig(BaseModel):
    input_file: Annotated[str, Arg(positional=True)]
    # Output path pattern needs final processing
    output_file_pattern: Annotated[Resolvable[str], Arg(
        resolvable=True, # Crucial: Tells CLI to wrap in Resolvable
        short='o',
        help="Output file pattern, e.g., '{input}.out'"
    )] = "{input}.processed" # Default pattern
```

**2. Parse CLI Arguments:**

```python
# main.py
import dracon as dr
from models import ProcessingConfig

program = dr.make_program(ProcessingConfig, context={'ProcessingConfig': ProcessingConfig})
config, _ = program.parse_args() # e.g., running with: python main.py data.csv -o {input}.result

# config.output_file_pattern is a Resolvable object here
print(type(config.output_file_pattern)) # <class 'dracon.resolvable.Resolvable'>
```

**3. Resolve the Value:**

```python
# ... application logic ...

# Call .resolve() on the Resolvable object, providing context if needed
# The context here allows the pattern string itself to use '{input}'
final_output_path = config.output_file_pattern.resolve(
    context={'input': config.input_file}
)

# Now final_output_path is the resolved string
print(f"Input: {config.input_file}")         # Output: data.csv
print(f"Output Path: {final_output_path}") # Output: data.csv.result
```

**Key Points for `Resolvable`:**

- Delays the final processing/validation of a _single field's value_.
- The main configuration object is already constructed.
- Requires calling `.resolve()` manually, providing context if the value's final form depends on it.
- Often used with `Arg(resolvable=True)` for CLI arguments needing post-parsing logic.
- The `Resolvable` object holds the original YAML node and the expected inner type `T`.

Choose `DeferredNode` to delay building a whole component, and `Resolvable` to delay finalizing a specific value within an already built structure. See [Deferred vs Resolvable Concepts](../concepts/deferred-resolvable.md).
