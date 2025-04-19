# Welcome to Dracon!

Dracon is a configuration system for Python applications built on top of YAML. It aims to solve common configuration headaches by adding powerful features for modularity, dynamic value generation, type safety, and even command-line interface creation.

Think of it as YAML++, supercharged for complex application needs.

## Why Use Dracon?

Plain YAML is great for simple configs, but as applications grow, you often run into challenges:

- **Repetition:** How do you share common settings across different parts of your config or different environments?
- **Dynamic Values:** How do you derive configuration values from environment variables, calculations, or other config keys?
- **Environment Management:** How do you manage distinct configurations for development, staging, and production without excessive duplication?
- **Secrets:** How do you safely include sensitive data?
- **Type Safety:** How do you ensure your configuration matches the types expected by your Python code?
- **CLI Integration:** How do you bridge the gap between config files and command-line arguments smoothly?

Dracon addresses these by providing:

- **Includes:** Load and merge configuration from files, Python packages, environment variables, and even other parts of the same document.
- **Interpolation:** Embed Python expressions directly into your YAML to compute values dynamically.
- **Merging:** Define precisely how different configuration sources should be combined using flexible merge strategies.
- **Pydantic Integration:** Leverage Pydantic models for robust type validation and easy object construction.
- **Deferred Nodes:** Control _when_ parts of your configuration are constructed, allowing for complex setup sequences.
- **CLI Generation:** Automatically build command-line interfaces directly from your Pydantic configuration models.

## Quick Start

Let's see a small example.

**1. Install Dracon:**

```bash
pip install dracon
```

**2. Define a Pydantic Model (e.g., `models.py`):**

```python
# models.py
from pydantic import BaseModel

class DatabaseConfig(BaseModel):
    host: str
    port: int
    username: str
```

**3. Create a Configuration File (`config.yaml`):**

```yaml
# config.yaml
app_name: MyAwesomeApp
log_level: ${getenv('LOG_LEVEL', 'INFO')} # Use an env var or default

database: !DatabaseConfig # Tells Dracon to use your Pydantic model
  host: localhost
  port: 5432
  # Include username from another file (e.g., for secrets)
  username: !include file:db_user.yaml
```

**4. Create `db_user.yaml`:**

```yaml
# db_user.yaml
admin
```

**5. Load the Configuration (`main.py`):**

```python
# main.py
from dracon import DraconLoader
from models import DatabaseConfig # Import your model

# Provide the model class in the context so Dracon can find it
loader = DraconLoader(context={'DatabaseConfig': DatabaseConfig})

# Load the main config file
config = loader.load('config.yaml')

# Access values - note that config.database is now a DatabaseConfig instance!
print(f"App Name: {config.app_name}")
print(f"Log Level: {config.log_level}")
print(f"Database Host: {config.database.host}")
print(f"Database Port: {config.database.port}")
print(f"Database User: {config.database.username}")

assert isinstance(config.database, DatabaseConfig)
```

**6. Run it:**

```bash
python main.py
```

This simple example demonstrates environment variable access (`${getenv(...)`), file inclusion (`!include`), and automatic Pydantic model construction (`!DatabaseConfig`).

## The Dracon Lifecycle: How it Works

Understanding how Dracon processes your configuration is key. It happens in several stages:

1.  **Input:** Dracon starts with your root YAML file(s), initial context, and potentially CLI arguments.
2.  **Composition Phase:** This is where Dracon's magic happens _before_ creating Python objects.
    - **YAML Parsing:** Reads the YAML structure using `ruamel.yaml`.
    - **Include Resolution:** Processes `!include` tags (and `*anchor` copies), fetching and inserting content from files, packages, environment variables, anchors, etc. This is recursive.
    - **Instruction Processing:** Executes directives like `!define`, `!if`, `!each` which modify the YAML node structure itself (e.g., adding context, removing nodes, generating multiple nodes).
    - **Merge Resolution:** Processes `<<:` merge keys, combining different YAML structures according to specified rules.
    - **(Internal Steps):** Prepares nodes for interpolation, handles deferred node wrapping.
3.  **Construction Phase:** Dracon builds the final Python objects from the composed YAML node tree.
    - Uses type tags (`!TypeName`) to determine the target Python class.
    - Leverages Pydantic for validation and construction if a model is specified.
    - Creates `LazyInterpolable` wrappers for `${...}` expressions.
    - Creates `Resolvable` wrappers if specified.
    - Builds standard Python dicts/lists or Dracon's `Mapping`/`Sequence` containers.
4.  **Runtime Phase:** Your Python code interacts with the loaded configuration object.
    - Accessing values triggers lazy evaluation of `${...}` expressions.
    - Calling `.construct()` on `DeferredNode` objects triggers their delayed composition and construction.
    - Calling `.resolve()` on `Resolvable` objects triggers their final processing.

This multi-stage process allows Dracon to handle complex dependencies and dynamic configurations effectively.

## Next Steps

Dive deeper into the core features:

- [Loading Configuration](loading.md)
- [Includes (Modularity)](includes.md)
- [Interpolation (Dynamic Values)](interpolation.md)
- [Merging Configurations](merging.md)
- [Instructions (Composition Logic)](instructions.md)
- [Working with Types](types.md)
