# Serialization

You need to dump a config back to YAML, or serialize config objects for storage or IPC.

## The four-peer model

Dracon splits both directions of the object-node-text pipeline into two named
steps, giving you four peers total:

| direction | semantic step                   | syntactic step       |
|-----------|---------------------------------|----------------------|
| load      | `compose(source)` -> Node       | `loads`/`load` -> value |
| dump      | `dump_to_node(value)` -> Node   | `dump` -> text       |

`dump_to_node` is the inverse of `construct`. Use it when you want a Node tree
for further processing (e.g. inserting a value as a layer into a
`CompositionStack`) rather than YAML text. `dump` is just
`emit(dump_to_node(value))` underneath, and both paths use the same
representer instance on a given loader.

```python
import dracon

node = dracon.dump_to_node(config)          # Node tree, same vocabulary as dump()
text = dracon.dump(config)                  # YAML text
```

Both `dump_to_node` and `dump` accept a `context=` kwarg for vocabulary-aware
tag emission; on a bound loader, both consult `loader.context` automatically.

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

config = DBConfig(host="db.prod.internal", port=5433)
print(dracon.dump(config))
# !mymodule.DBConfig
# host: db.prod.internal
# port: 5433
```

Note that by default `exclude_defaults=True`, so fields equal to their Pydantic default value are omitted from the dump. To include all fields, set `exclude_defaults=False` on the representer (see [Controlling representation](#controlling-representation)).

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

## Vocabulary-driven tag emission

A `DraconLoader`'s `context` is a `SymbolTable` — the same object the
load path uses to resolve tags back into types. On the dump side, the
representer consults that same table to pick a canonical short name for
any value whose type is registered. Two projects that bind the same
Python class under different names emit different tags:

```python
vocab_a = SymbolTable()
vocab_a.define(SymbolEntry(name="Server", symbol=CallableSymbol(Host, name="Server")))

vocab_b = SymbolTable()
vocab_b.define(SymbolEntry(name="Node", symbol=CallableSymbol(Host, name="Node")))

host = Host(name="h1", cpus=8)
loader_a = DraconLoader(); loader_a.context = vocab_a
loader_b = DraconLoader(); loader_b.context = vocab_b

loader_a.dump(host)   # !Server\nname: h1\ncpus: 8\n
loader_b.dump(host)   # !Node\nname: h1\ncpus: 8\n
```

`SymbolTable.identify(value)` walks the MRO, so subclasses of a
registered type emit the nearest canonical base name. Only entries
added via `define()` / `set_default()` participate in identification —
captured globals (assigned via `table[k] = v`) stay invisible, which
prevents accidental renames from polluting the dump side.

`full_module_path` only controls the *fallback*: when a value is not in
the vocabulary, dracon falls back to a qualname-based tag, and
`full_module_path=True` (the default) produces the fully qualified
form.

## Wrapper round-trip

All dracon-native wrapper types round-trip through dump/load, including
when they are nested inside pydantic models, plain dicts, and lists:

- `DeferredNode` — emits the `!deferred` tag; a loaded deferred can be
  dumped again without recursion, even when it contains more
  `DeferredNode`s inside.
- `Resolvable[T]` — emits `!Resolvable[T]` and reloads as a
  `Resolvable`, never as a bare `T`.
- `LazyInterpolable` — emits its `${expr}` source, not the resolved
  value.
- `DraconCallable` (`!fn` templates), `DraconPipe`, `BoundSymbol`,
  `DraconPartial` — all emit under their own tags and round-trip to
  invokable forms.

The pinning contract is:

```
loads(dump(x, V), V) ≅ x
```

for any value `x` in vocabulary `V`. Pydantic fields of type `dict`,
`list`, or `Any` preserve any wrapper values they contain — there is no
flattening pass, so broodmon-style walkers are unnecessary.

## Line-framed streams

For wire protocols, log-replay streams, and IPC pipes, use
`dump_line` / `loads_line` / `document_stream`:

```python
from dracon import dump_line, loads_line, document_stream

line = dump_line(event, context=vocab)      # -> bytes, ends with '\n'
reloaded = loads_line(line, context=vocab)

async for doc in document_stream(reader, context=vocab):
    handle(doc)
```

`dump_line` collapses to single-line flow-style YAML. If a value cannot
be expressed on one line (e.g. a top-level literal scalar with an
embedded newline), `NotLineableError` fires loudly instead of silently
corrupting the frame.

## Node construction helpers

`DraconDumpable` implementations previously had to import ruamel node
classes and tag constants. Three helpers make that invisible:

```python
from dracon.nodes import make_scalar_node, make_sequence_node, make_mapping_node
from dracon.representer import DraconDumpable

class Point3D(DraconDumpable):
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z

    def dracon_dump_to_node(self, representer):
        return make_mapping_node(
            {
                "x": make_scalar_node(str(self.x), tag="tag:yaml.org,2002:int"),
                "y": make_scalar_node(str(self.y), tag="tag:yaml.org,2002:int"),
                "z": make_scalar_node(str(self.z), tag="tag:yaml.org,2002:int"),
            },
            tag="!Point3D",
        )
```

`make_mapping_node` accepts either an iterable of `(key_node, value_node)`
tuples or a plain dict whose keys are strings (auto-wrapped in scalar
nodes). Pick whichever reads best for your case.
