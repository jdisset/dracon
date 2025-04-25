# How-To: Load Configuration Files

Dracon provides several ways to load YAML configuration files.

## Loading a Single File

The simplest way is using the top-level `dracon.load` function:

```python
import dracon as dr
from pydantic import BaseModel

# Assume MyConfig is defined
# class MyConfig(BaseModel): ...

# Load the file, Dracon attempts to parse and validate
# If config.yaml starts with !MyConfig, it will return a MyConfig instance
config = dr.load("path/to/config.yaml", context={'MyConfig': MyConfig})

# Access data
print(config.some_key)
```

You can also use the `DraconLoader` class directly for more control:

```python
from dracon import DraconLoader

loader = DraconLoader(context={'MyConfig': MyConfig})
config = loader.load("path/to/config.yaml")
```

## Loading from a String

Use `dracon.loads`:

```python
import dracon as dr

yaml_string = """
key: value
nested:
  level: 1
"""
config = dr.loads(yaml_string)
print(config.nested.level) # Output: 1
```

## Loading Multiple Files (Merging)

Provide a list of file paths to `dracon.load`. Dracon loads them sequentially, merging each subsequent file onto the result of the previous ones.

```python
import dracon as dr

# Loads base.yaml, then merges prod.yaml onto it
config = dr.load(
    ["config/base.yaml", "config/prod.yaml"],
    context={...} # Provide context if models are used
)
```

By default, the merge strategy is `<<{<+}[<~]` (recursive append for dicts, new wins; replace lists, new wins). You can customize this:

```python
# Example: Append lists instead of replacing, existing wins
config = dr.load(
    ["config/base.yaml", "config/prod.yaml"],
    merge_key="<<{<+}[+>]", # Dict: new wins, List: append existing first
    context={...}
)
```

See the [Merging Configurations](merge-configs.md) guide and [Merging Concepts](../concepts/composition.md#merging-configurations) for details on merge strategies.

## Loading via CLI (`+` prefix)

When using Dracon's [CLI generation](../concepts/cli.md), arguments starting with `+` are treated as configuration files to load and merge _before_ applying other CLI overrides.

```bash
# Load base.yaml, then merge prod.yaml, then apply CLI overrides
$ python your_app.py +base.yaml +prod.yaml --some-arg value
```

The files are merged in the order they appear on the command line, using the default merge strategy (`<<{<+}[<~]`).

## Loading from Different Sources

While `load("path")` assumes a file, you can be explicit or load from other sources using prefixes, especially within `!include` directives or when providing file paths as CLI argument values:

- `file:path/to/file.yaml`: Load from filesystem (relative paths resolved based on the including file or CWD).
- `pkg:package_name:path/to/resource.yaml`: Load from resources within an installed Python package.
- `env:VARIABLE_NAME`: Load the value directly from an environment variable (used with `!include`).

See the [Includes guide](use-includes.md) for more details.
