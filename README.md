# Dracon

built around sensible and natural-feeling YAML extensions.

# Configuration Library for Extended YAML Parsing

Dracon is a simple modular configuration system that extends YAML parsing in Python (leveraging some of the great work at `ruamel.yaml`). It provides advanced features for configuration files, including:

- 📂 Inclusion of other configuration files and variables.
- 🔄 Extended merge syntax for complex data merging.
- 🧮 Interpolation of simple Python expressions within the configuration.
- 🧩 Resolvable nodes for deferred construction and advanced manipulation.
- 🛠️ Automatic construction and instantiation of python objects using Pydantic.
- 🖥️ Command line programs configurable through files and command line arguments overrides.

## Features

### 1. Inclusion of Other Configuration Files and Variables

You can include external YAML files or variables directly within your configuration using the `!include` tag or the `*loader:` syntax.

#### Syntax

- **Using `!include` tag:**

  ```yaml
  settings: !include "file:config/settings.yaml"
  ```

- **Using `*loader:` syntax:**

  ```yaml
  settings: *file:config/settings.yaml
  ```

#### Supported loaders

- `file:` - Loads a file from the filesystem.
- `env:` - Loads an environment variable.
- `pkg:` - Loads a resource from a Python package.

You can also write a custom loader to support other sources.

#### Examples

**Including a file:**

```yaml
database: !include "file:config/database.yaml"
```

**Including an environment variable:**

```yaml
api_key: *env:API_KEY
```

**Including a package resource:**

```yaml
defaults: !include "pkg:my_package:configs/defaults.yaml"
```

**Including a specific key from an included file:**

```yaml
specific_setting: *file:config/settings.yaml@setting_key
```

### 2. Extended Merge Syntax

The library extends the YAML merge key `<<` to provide advanced merging capabilities with customizable behavior.

#### Merge Key Syntax

```yaml
<<{dict_options}[list_options]@keypath: value
```

- `{dict_options}`: Options for merging dictionaries.
- `[list_options]`: Options for merging lists.
- `@keypath`: Optional keypath to specify where to apply the merge.

#### Options

- **Modes:**
  - `+`: Append (recursive merge).
  - `~`: Replace.
- **Priorities:**
  - `<`: New value has priority.
  - `>`: Existing value has priority.
- **Depth:**
  - Numbers (e.g., `+2`) to limit the depth of recursion.

#### Examples

**Basic merge with append and existing value priority:**

```yaml
<<{+>}: *file:base.yaml
```

**Merge and replace with new value priority:**

```yaml
<<{~<}: *file:override.yaml
```

**Merge at a specific keypath:**

```yaml
<<{+>}@settings.database: *file:database_override.yaml
```

**Merging lists with append:**

```yaml
<<[+]: [item4, item5]
```

### 3. Interpolation of Python Expressions

Embed Python expressions within your YAML configuration using `${expression}` syntax. The expressions are evaluated at load time.

|[!WARNING]

> Use caution when using interpolation, especially when loading untrusted configuration files.
> Dracon uses asteval to add some guardrails, but it's not hackproof, just merely "foolproof" (and probably not even that - let's not underestimate ourselves).

#### Syntax

```yaml
value: ${python_expression}
```

#### Examples

**Basic arithmetic:**

```yaml
sum: ${2 + 2} # Evaluates to 4
```

**Using variables from the context:**

```yaml
greeting: ${'Hello, ' + @name + '!'}
name: "World"
```

**Accessing other configuration values using keypaths:**

```yaml
full_name: ${first_name + ' ' + @/last_name}
first_name: "John"
last_name: "Doe"
```

**Interpolating tags:**

```yaml
number: !${'int'} ${2.1 + 3.1}  # Evaluates to integer 5
```

### 4. Resolvable Nodes

Resolvable nodes allow deferred construction of objects, enabling advanced manipulation and custom processing before the final object is created.

#### Syntax

```yaml
object: !Resolvable[Type]
  attribute1: value1
  attribute2: value2
```

#### Examples

**Deferring the construction of a custom object:**

```yaml
person: !Resolvable[Person]
  name: 'Alice'
  age: ${30 + 5}
```

In your Python code, you can resolve the object when needed:

```python
resolved_person = config.person.resolve()
```

### 5. Custom Tags and Types

You can use type tags to specify custom Python classes for objects in your configuration. They will be resolved and validated using Pydantic.

#### Syntax

```yaml
custom_object: !my_module.MyClass
  attr1: value1
  attr2: value2
```

#### Example

**Using a custom class:**

```yaml
database_config: !my_project.config.DatabaseConfig
  host: "localhost"
  port: 5432
```

## Order of Operations and Processing Stages

Understanding the order in which the configuration is processed helps in predicting the final outcome. The processing involves several stages:

1. **Composition Phase:**

   - **Parsing YAML Nodes:** The YAML content is parsed into a tree of nodes.
   - **Recording Special Nodes:** Include nodes (`!include`) and merge nodes (`<<`) are recorded along with their keypaths.

2. **Include Processing:**

   - **Resolving Include Nodes:** Include nodes are processed, and their content is recursively composed.
   - **Merging Included Content:** The included content replaces the include nodes in the configuration tree.

3. **Merge Processing:**

   - **Sorting Merge Nodes:** Merge nodes are sorted to ensure that merges occur from the deepest nodes upwards.
   - **Applying Merges:** Merges are applied according to the specified options, modifying the configuration tree.

4. **Construction Phase:**
   - **Constructing Python Objects:** The nodes are transformed into Python objects.
   - **Interpolation:** Python expressions (`${...}`) are evaluated during object construction.
   - **Resolving Resolvable Nodes:** Resolvable nodes are constructed when their `resolve()` method is called.

## Key Concepts

- **Nodes:** The raw representation of the YAML content before construction.
- **Keypaths:** Paths that identify the location of nodes within the configuration tree.
- **Composition Result:** The state of the configuration after the composition phase, including the root node and recorded include and merge nodes.
- **Construction Result:** The final Python objects constructed from the nodes, after interpolation and processing.

## Usage Example

**config.yaml**

```yaml
# Include base settings
<<: *file:config/base.yaml

# Override a setting with interpolation
database:
  host: ${'db.' + env}

# Use a custom object
service: !my_project.ServiceConfig
  name: 'ExampleService'
  port: 8080
```

**Python Code**

```python
from dracon.loader import DraconLoader

# Create a loader instance
loader = DraconLoader()

# Load the configuration
config = loader.load('config.yaml')

# Access configuration values
print(config.database.host)
print(config.service.name)
```

### 6. Command Line Programs

Dracon provides utilities to generate command line programs from a simple Pydantic model. They fully leverage the configuration system and allow for easy configuration file overrides and command line argument parsing.

```
Arg annotation:
        real_name: Optional[str] = None # autofill
        short: Optional[str] = None
        long: Optional[str] = None # default = real_name
        help: Optional[str] = None # help message, displayed with -h or --help
        arg_type: Optional[type] = None # autofill
        expand_help: Optional[bool] = False
        action: Optional[Callable[[ProgramType, Any], Any]] = None # function to call after initialization
        positional: Optional[bool] = False
        resolvable: Optional[bool] = False
        is_file: Optional[bool] = False
```

```yaml
# base_config.yaml
database:
    host: "remotehost"
    port: 543
```
```yaml
# partial_config_override.yaml
database:
    port: 5432
    user: *env:DB_USER
    password: *env:DB_PASSWORD
use_ssl: false
```
```python

from typing import Annotated
from pydantic import BaseModel
from dracon import Arg, make_program

class DatabaseConfig(BaseModel):
    host: str
    port: int
    user: str
    password: str

class MyProgramModel(BaseModel):
    database: Annotated[DatabaseConfig, Arg(
        help='Database configuration',
        short='d',
        expand_help=True,
    )]
    use_ssl: Annotated[bool, Arg(
        help='Use SSL for connection',
        short='s',
    )]

    def run(self):
        # everything is already validated and filled in
        ...

prog = dracon.make_program(
    MyProgramModel, # Pydantic model
    name='my-program',
    description='Description of my program.',
)
program_model, args = prog.parse_args(sys.argv[1:])

# program_model is an instance of MyProgramModel
# with all its fields filled
# example invocation:
# python my_program.py +base_config.yaml +partial_config_override.yaml --database.host localhost --use_ssl

assert program_model.database.host == 'localhost'
assert program_model.use_ssl == True
assert program_model.database.port == 5432

program_model.run() # call whatever method you want to run
```

## Misc Advanced Features

### Lazy Interpolation

If a constructed object implements the DraconLazy protocol (easiest is probably to inherit from LazyDraconModel), any interpolable fields will be kept unevaluated until accessed.
When construcing a class that does not implement the DraconLazy protocol (like a vanilla dict for example), all interpolable fields will be evaluated immediately.

### Interpolating Tags and Values Together

You can interpolate both the tag and the value in a node:

```yaml
dynamic_value: !${'int'} ${2 + 3}  # Evaluates to integer 5
```

### Using Keypaths in Interpolation

Keypaths allow you to reference other parts of the configuration during interpolation:

```yaml
combined_value: ${@/some/other/value + 10}
```

### Customizing Merge Behavior

Control merge operations with depth limits and priority settings:

```yaml
# Limit merge recursion depth and set priorities
<<{+2<}[~>]: *file:config/partial_override.yaml
```
