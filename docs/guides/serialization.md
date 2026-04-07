# Serialization

You need to dump a config back to YAML, or serialize config objects for storage or IPC.

## dracon.dump()

The `dump()` function serializes any config object to a YAML string:

```python
import dracon

config = dracon.loads("""
database:
  host: localhost
  port: 5432
""")

yaml_str = dracon.dump(config)
print(yaml_str)
```

It handles:

- **Pydantic models**: dumped with their type tag (e.g. `!mymodule.MyModel`)
- **Dracontainers**: Dracon's dict/list wrappers serialize transparently
- **Enums**: serialized by their `.value`
- **Dataclasses**: treated like dicts
- **DeferredNodes**: serialized with the `!deferred` tag reconstructed, including any `clear_ctx` or type hint suffixes
- **numpy arrays**: serialized as flow-style YAML lists
- **Primitives, dicts, lists**: the usual

### Tags are preserved

When you dump a Pydantic model, the tag reflects its fully qualified class path:

```python
class DBConfig(BaseModel):
    host: str = "localhost"
    port: int = 5432

config = DBConfig()
print(dracon.dump(config))
# !mymodule.DBConfig
# host: localhost
# port: 5432
```

## Round-trip: load, modify, dump

You can load a config, change it, and dump it back:

```python
config = dracon.loads("""
database:
  host: localhost
  port: 5432
""")

config['database']['port'] = 5433

yaml_str = dracon.dump(config)
config2 = dracon.loads(yaml_str)

assert config2['database']['port'] == 5433
```

This works because Dracon's representer knows how to turn constructed objects back into YAML nodes.

## DraconDumpable protocol

If you have a custom class and want to control how it serializes to YAML, implement the `DraconDumpable` protocol:

```python
from dracon.representer import DraconDumpable

class MyThing:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def dracon_dump_to_node(self, representer):
        # return a ruamel.yaml Node
        return representer.represent_mapping(
            '!MyThing',
            {'x': self.x, 'y': self.y}
        )
```

The representer calls `dracon_dump_to_node` automatically when it encounters an object that implements the protocol. The method receives the `DraconRepresenter` instance, so you can use its `represent_mapping`, `represent_sequence`, and `represent_scalar` methods to build the node.

## Pickle support

Some Dracon types are picklable, some aren't:

| Type | Picklable | Notes |
|---|---|---|
| `DraconPartial` | Yes | Stores function as importable dotted path string |
| `DraconCallable` | No | Contains YAML node templates and loader references |
| Dracontainers | Yes | If all contained values are picklable |
| Pydantic models | Yes | Standard Pydantic pickling |
| `DeferredNode` | Yes | Stores the full composition state |
| `LazyInterpolable` | Yes | Stores expression string and context |

If you need to serialize a `DraconCallable`, dump it to YAML first with `dracon.dump()`, then load it back in the target process. `DraconPartial` (created by `!fn:dotted.path`) is the picklable alternative: it stores the function as an import path and reconstructs it on unpickling.

## Writing to a file

Pass a stream to `dump()` to write directly to a file:

```python
with open('output.yaml', 'w') as f:
    dracon.dump(config, stream=f)
```

## Controlling representation

The `DraconRepresenter` accepts two options:

- `full_module_path=True` (default): tags include the full module path, e.g. `!mypackage.mymodule.MyClass`
- `exclude_defaults=True` (default): fields equal to their Pydantic default are omitted from the dump

These are set on the representer, not on `dump()` directly. If you need to customize them, create a `DraconLoader` and configure its representer:

```python
loader = dracon.DraconLoader()
loader.yaml.representer.full_module_path = False
loader.yaml.representer.exclude_defaults = False
yaml_str = loader.dump(config)
```
