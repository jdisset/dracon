# Working with Types

Dracon leverages YAML tags (`!TypeName`) and integrates closely with Pydantic to provide type validation and construct specific Python objects from your configuration.

## Specifying Types with Tags

You can tell Dracon what kind of Python object to create from a YAML node by prefixing it with a tag.

```yaml
# Standard YAML tags for built-in types
count: !int "10" # Constructed as Python int 10
pi: !float "3.14159" # Constructed as Python float 3.14159
message: !str 123 # Constructed as Python str "123"
enabled: !bool "true" # Constructed as Python bool True

# Tag for a custom or Pydantic type
database: !DatabaseConfig # Dracon will look for DatabaseConfig
  host: localhost
  port: 5432
```

## Type Resolution

When Dracon encounters a tag like `!DatabaseConfig` or `!my.package.utils.HelperClass`, it tries to find the corresponding Python class (`DatabaseConfig` or `HelperClass`) using the following search order:

1.  **DraconLoader Context:** Checks the `context` dictionary passed during `DraconLoader` initialization. This is the primary way to make your custom classes known.
    ```python
    from my_models import DatabaseConfig, CacheConfig
    loader = DraconLoader(context={
        'DatabaseConfig': DatabaseConfig,
        'CacheConfig': CacheConfig
    })
    ```
2.  **Default Known Types:** Checks built-in Dracon types like `Resolvable`.
3.  **Standard Modules:** Looks in common modules like `typing`, `pydantic`.
4.  **Package/Module Import:** If the tag includes a package path (`!my.package.MyClass`), Dracon attempts to import `my.package` and find `MyClass` within it.
5.  **Fallback Resolution:** Uses internal Python mechanisms (`typing._eval_type`) as a last resort.

!!! tip
Always prefer adding your custom types to the `DraconLoader` context for reliable resolution.

## Pydantic Integration

Dracon's integration with Pydantic is seamless and powerful:

1.  **Tag Matching:** If the resolved type for a tag (e.g., `!DatabaseConfig`) is a Pydantic `BaseModel`, Dracon uses it.
2.  **Data Construction:** Dracon first constructs the YAML node into a basic Python type (usually a `dict` for mappings).
3.  **Pydantic Validation:** It then passes this dictionary to Pydantic's validation machinery (`TypeAdapter(YourModel).validate_python(data)`).
4.  **Result:** You get a fully validated Pydantic model instance. All of Pydantic's features work, including type coercion, default values, validation errors, computed fields, etc.

```python
# models.py
from pydantic import BaseModel, Field
from typing import Optional

class Server(BaseModel):
    host: str
    port: int = 8080 # Pydantic default
    protocol: str = Field(default="http")

# config.yaml
server: !Server # Use the Server model
  host: "api.example.com"
  # port is omitted, Pydantic default 8080 will be used
  protocol: "https" # Overrides Pydantic default

# main.py
from dracon import DraconLoader
from models import Server

loader = DraconLoader(context={'Server': Server})
config = loader.load('config.yaml')

assert isinstance(config.server, Server)
assert config.server.host == "api.example.com"
assert config.server.port == 8080 # Default used
assert config.server.protocol == "https" # Value from YAML used
```

## Custom Types (Non-Pydantic)

You can use tags for your own non-Pydantic classes too.

- **Loading (`!MyClass`)**:

  - Make the class available via the `context`.
  - Dracon will construct the node's data (e.g., into a `dict`).
  - It will then attempt to call `MyClass(constructed_data)`.
  - Your class's `__init__` method must be able to handle the input type (e.g., accept a dictionary for mapping nodes).

- **Dumping (Serialization)**:
  - By default, Dracon uses `ruamel.yaml`'s standard representation.
  - To customize serialization, implement a `dracon_dump_to_node(self, representer)` method in your class. This method should return the desired `ruamel.yaml` node representation (e.g., `representer.represent_mapping('!MyClass', {'attr': self.attr})`).

```python
# custom_types.py
class Point:
    # yaml_tag = '!Point' # Optional: For auto-registration later if needed

    def __init__(self, data): # __init__ handles dict input
        self.x = data.get('x', 0)
        self.y = data.get('y', 0)

    def __repr__(self):
        return f"Point(x={self.x}, y={self.y})"

    # Optional: Custom serialization hook
    def dracon_dump_to_node(self, representer):
        # Represent as a !Point mapping
        return representer.represent_mapping(
            '!Point', {'x': self.x, 'y': self.y}
        )

# config.yaml
start_point: !Point
  x: 10
  y: 20

# main.py
from dracon import DraconLoader
from custom_types import Point

loader = DraconLoader(context={'Point': Point})
config = loader.load('config.yaml')

assert isinstance(config.start_point, Point)
assert config.start_point.x == 10

# Dumping will use dracon_dump_to_node if available
print(loader.dump({'p': config.start_point}))
# Output:
# p: !Point
#   x: 10
#   y: 20
```

## Dynamic Tags (`!$(...)`)

You can use [immediate interpolation](interpolation.md#2-immediate-interpolation--) to dynamically determine the tag applied to a node based on context available at parse time.

```yaml
!define shape_type: ${'Circle' if radius > 0 else 'Point'}

# The tag (!Circle or !Point) is determined when this is parsed
my_shape: !$(shape_type) # Fields relevant to Circle or Point...
  radius: ${radius} # Assuming radius is in context
  x: 0
  y: 0
```
