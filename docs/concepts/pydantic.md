# Concepts: Pydantic Integration

Dracon's integration with Pydantic is a cornerstone feature, enabling type-safe, validated, and structured configuration management.

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

```python
# models.py
from pydantic import BaseModel, Field, validator

class Server(BaseModel):
    host: str
    port: int = 8080 # Pydantic default

    @validator('port')
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
