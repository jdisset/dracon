# Advanced Usage

## Deferred Nodes

Deferred nodes are nodes of the configuration object that are not constructed immediately when the config is loaded. Instead, they are kept in their raw node form, and will require an explicit call to their `construct` method to be constructed.

It can be pretty useful in a few situations.

An example is when you need to add some context in order to properly construct this node (for example some variable has to be defined), but you need to first load the rest of the configuration to know what this variable should be.

```yaml
# config.yaml
password_path: /path/to/credentials.txt

!deferred(DB) database:
  host: "localhost"
  port: 5432
  password: ${password}
```

```python
from dracon import DraconLoader, DeferredNode
from pydantic import BaseModel

class DB(BaseModel):
    host: str
    port: int
    password: str

loader = DraconLoader(context={'DB': DB})
config = loader.load('config.yaml')

assert isinstance(config.database, DeferredNode[DB])

password = open(config.password_path).read().strip()

config.database = config.database.construct({'password': password})

assert isinstance(config.database, DB)
```
