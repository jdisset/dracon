# How-To: Use Pydantic Models

Dracon integrates tightly with Pydantic, allowing you to define, validate, and construct your configuration using familiar Pydantic models.

## Tagging Nodes with Model Names

Use a YAML tag matching your Pydantic model's name (prefixed with `!`) to instruct Dracon to use that model for construction and validation.

```yaml
# config.yaml
database: !DatabaseConfig # Use the DatabaseConfig model
  host: "db.prod.svc"
  port: 5433 # Override default
  username: "prod_user"
  # password missing, will cause validation error if required

server: !ServerConfig # Use the ServerConfig model
  address: "0.0.0.0"
  # threads missing, will use Pydantic default if defined
```

## Providing Models to the Loader

Dracon needs to know about your Pydantic models to resolve the tags. Provide them via the `context` argument when creating `DraconLoader` or calling `dracon.load`/`loads`.

```python
# models.py
from pydantic import BaseModel

class DatabaseConfig(BaseModel):
    host: str
    port: int = 5432 # Pydantic default
    username: str
    password: str    # Required field

class ServerConfig(BaseModel):
    address: str
    threads: int = 4 # Pydantic default

# main.py
import dracon as dr
from models import DatabaseConfig, ServerConfig

# Provide models in the context dictionary
loader = dr.DraconLoader(context={
    'DatabaseConfig': DatabaseConfig,
    'ServerConfig': ServerConfig
})

try:
    # Load the YAML from the previous step
    config = loader.load("config.yaml")

    # Access data via validated Pydantic instances
    assert isinstance(config.database, DatabaseConfig)
    assert isinstance(config.server, ServerConfig)

    print(f"DB Host: {config.database.host}") # Output: db.prod.svc
    print(f"DB Port: {config.database.port}") # Output: 5433 (from YAML)

    print(f"Server Address: {config.server.address}") # Output: 0.0.0.0
    print(f"Server Threads: {config.server.threads}") # Output: 4 (Pydantic default)

except Exception as e:
    # If validation fails (e.g., missing password), Pydantic/Dracon raises an error
    print(f"Configuration Error: {e}")

```

## How it Works

1.  **Tag Resolution:** Dracon sees `!DatabaseConfig`, looks it up (first in `context`, then other places), and finds the `DatabaseConfig` class.
2.  **YAML Construction:** It constructs the YAML node into a basic Python `dict` (or list/scalar).
3.  **Pydantic Validation:** It passes the constructed `dict` to Pydantic (`DatabaseConfig.model_validate(the_dict)`).
4.  **Instance Creation:** Pydantic performs type coercion, applies defaults, runs validators, and returns a validated `DatabaseConfig` instance.
5.  **Result:** The value associated with the `database:` key in your final configuration object _is_ the `DatabaseConfig` instance.

## Benefits

- **Type Safety:** Catch configuration errors early.
- **Defaults:** Define defaults in one place (your Pydantic model).
- **Validation:** Use Pydantic's powerful validation capabilities.
- **IDE Support:** Get autocompletion and type checking for your configuration object.
- **CLI Integration:** Pydantic models super useful for Dracon's [automatic CLI generation](customize-cli.md).

See [Pydantic Integration Concepts](../concepts/pydantic.md) for more details.
