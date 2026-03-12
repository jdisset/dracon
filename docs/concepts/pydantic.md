# Concepts: Pydantic Integration & Custom Types

## The Role of Pydantic

Pydantic provides data validation and settings management using Python type annotations. By integrating with Pydantic, Dracon leverages these capabilities for configuration:

- **Schema Definition:** Define the expected structure, types, and constraints of your configuration using Pydantic `BaseModel`s.
- **Validation:** Automatically validate loaded configuration data against your models, catching errors like incorrect types or missing required fields early.
- **Type Coercion:** Pydantic handles converting types where appropriate (e.g., a string "42" in YAML can become an integer `42` if the model field is `int`).
- **Defaults:** Define default values directly in your Pydantic models.
- **Construction:** Dracon constructs instances of your Pydantic models from the validated YAML data.

## How Integration Works

1.  **Tagging (`!YourModelName`):** You mark a YAML node with a tag corresponding to your Pydantic model name (e.g., `!DatabaseConfig`).
2.  **Context:** You provide the Pydantic model class(es) to the `DraconLoader` via its `context` dictionary (e.g., `context={'DatabaseConfig': DatabaseConfig}`). This allows Dracon to find the class when it encounters the tag.
3.  **YAML Construction:** Dracon first parses the tagged YAML node and its children into basic Python types (typically a dictionary for a mapping node).
4.  **Pydantic Validation:** Dracon then passes this intermediate dictionary to Pydantic's `TypeAdapter` (effectively calling `YourModel.model_validate(intermediate_dict)`).
5.  **Instance Creation:** Pydantic validates the data against the model definition:
    - Checks required fields are present.
    - Coerces types according to field annotations.
    - Applies default values for missing optional fields.
    - Runs any custom validators defined on the model.
    - If validation succeeds, Pydantic creates an instance of `YourModel`.
    - If validation fails, a `ValidationError` is raised, typically surfaced by Dracon.
6.  **Result:** The constructed and validated Pydantic model instance becomes the value associated with the key in the final configuration object returned by Dracon.

!!! tip
    The type tag `!YourModelName` will check for this class in the context dictionary. You can also use a full path to the type (e.g., `!mypackage.models.Server`) if you prefer, which lifts the type-in-context requirement. 
    

!!! note
    You don't _have_ to use pydantic models with Dracon. They just work out-of-the box. However, you can also use your custom types. By default Dracon will try to feed the dictionnary of the YAML node to the constructor of your custom type. If you want to use a different approach, you can define your own representer and constructor for your custom type. See ruamel.yaml's doc for more information on that.

```python
# models.py
from pydantic import BaseModel, Field, field_validator

class Server(BaseModel):
    host: str
    port: int = 8080 # Pydantic default

    @field_validator('port')
    @classmethod
    def port_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('Port must be positive')
        return v

# config.yaml
server: !Server # Tag instructs Dracon to use the Server model
  host: "api.example.com"
  # Port omitted - Pydantic default 8080 will be used after validation

# main.py
import dracon as dr
from models import Server

loader = dr.DraconLoader(context={'Server': Server})
config = loader.load('config.yaml')

assert isinstance(config.server, Server)
assert config.server.host == "api.example.com"
assert config.server.port == 8080 # Default applied by Pydantic
```

## `LazyDraconModel`: Lazy Interpolation in Pydantic Models

When you load YAML with `${...}` expressions into standard Pydantic models, dracon resolves all interpolations eagerly during construction. This is fine most of the time, but sometimes you want field values to remain unresolved until you actually access them — for example, when the context needed for resolution isn't available at load time.

`LazyDraconModel` is a `BaseModel` subclass that defers `${...}` resolution to attribute access time. Fields can hold `LazyInterpolable` objects that survive pydantic validation and resolve transparently when you read them.

```python
from dracon import LazyDraconModel
from typing import Annotated

class ServerConfig(LazyDraconModel):
    host: str = "server-${instance}.example.com"
    port: int = 8080
```

```yaml
# config.yaml
server: !ServerConfig
  host: "db-${region}.internal"
```

```python
config = dr.load("config.yaml", context={
    'ServerConfig': ServerConfig,
    'region': 'us-east-1',
})

# interpolation resolves here, on access:
print(config.server.host)  # -> "db-us-east-1.internal"
```

### How it works

Two mechanisms cooperate:

1. **`ignore_lazy` field validator** — when pydantic receives a `LazyInterpolable` value for a field (e.g., a `str` field gets a lazy object), the validator stores it as-is instead of rejecting it, and captures the field's type validator for later.

2. **`__getattribute__` override** — when you access a field, if the stored value is a `Lazy` object, it resolves the interpolation on the fly using the model's root object and keypath context, then returns the resolved value.

### When to use it

- **Default:** Use `BaseModel`. Eager resolution is simpler and covers most cases.
- **Use `LazyDraconModel`** when field defaults contain `${...}` expressions that depend on context not yet available at construction time, or when you want resolution deferred to access time.

### With CLI subcommands

`LazyDraconModel` works as a subcommand model base. Field defaults containing `${...}` are resolved using the program's context:

```python
from dracon import dracon_program, Arg, Subcommand, LazyDraconModel
from pydantic import BaseModel
from typing import Annotated, Literal

class TrainCmd(LazyDraconModel):
    action: Literal['train'] = 'train'
    output_dir: Annotated[str, Arg(help="Output directory")] = "${BASE_DIR}/training"
    epochs: int = 10

@dracon_program(name="ml-tool", context={'BASE_DIR': '/results'})
class CLI(BaseModel):
    command: Subcommand(TrainCmd)

# ml-tool train → output_dir resolves to "/results/training"
```

!!! note
    The discriminator field (`action: Literal['train']`) must still be a plain `Literal` — dracon automatically excludes it from the lazy validator to satisfy pydantic's discriminated union requirements.
