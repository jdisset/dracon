# Extending Dracon

You need a custom instruction tag or a custom include loader.

## Custom instruction tags

Instruction tags are processed during composition. They can transform the YAML tree before construction. Built-in examples include `!define`, `!if`, `!each`, `!assert`, and `!require`.

### The Instruction class

Subclass `Instruction` and implement two methods:

```python
from dracon.instructions import Instruction, register_instruction
from dracon.composer import CompositionResult
from dracon.keypath import KeyPath

class ValidatePort(Instruction):
    """Check that a port value is in a valid range during composition."""

    @staticmethod
    def match(value):
        if value == '!validate_port':
            return ValidatePort()
        return None

    def process(self, comp_res: CompositionResult, path: KeyPath, loader):
        from dracon.instructions import unpack_mapping_key
        from dracon.diagnostics import CompositionError

        key_node, value_node, parent_node = unpack_mapping_key(
            comp_res, path, 'validate_port'
        )

        # evaluate the value to get the actual port number
        port_value = value_node.value
        if isinstance(port_value, str) and port_value.isdigit():
            port_value = int(port_value)

        if not isinstance(port_value, int) or not (1 <= port_value <= 65535):
            raise CompositionError(
                f"Invalid port: {port_value} (must be 1-65535)"
            )

        # remove the instruction key from the parent mapping
        del parent_node[str(path[-1])]

        return comp_res
```

### Registering

```python
register_instruction('!validate_port', ValidatePort)
```

The `!` prefix is added automatically if you forget it, so `register_instruction('validate_port', ValidatePort)` also works.

### Using it

```yaml
server:
  !validate_port port: 8080
  host: 0.0.0.0
```

During composition, `ValidatePort.process()` runs. If the port is out of range, you get a `CompositionError`.

### match() details

The `match()` method receives the tag string (e.g., `'!validate_port'`) and returns either an `Instruction` instance or `None`. This lets you support parameterized tags:

```python
@staticmethod
def match(value):
    import re
    m = re.match(r'!validate_range\((\d+),(\d+)\)', value)
    if m:
        return ValidateRange(int(m.group(1)), int(m.group(2)))
    return None
```

### Deferred instructions

Set `deferred = True` on your class to make the instruction run *after* all regular instructions, during the assertion pass. This is how `!assert` works:

```python
class MyCheck(Instruction):
    deferred = True  # runs after !define, !if, !each, etc.

    @staticmethod
    def match(value):
        ...

    def process(self, comp_res, path, loader):
        ...
```

## Custom include loaders

Dracon's `!include` tag supports scheme-prefixed paths like `file:`, `pkg:`, `env:`, `var:`. You can add your own schemes.

### Loader function signature

A loader function takes a path string and returns a tuple of `(content_string, context_dict)`:

```python
def my_loader(path, node=None, draconloader=None):
    """
    Args:
        path: the part after the scheme prefix (e.g., "secret/data/myapp#password"
              for "vault:secret/data/myapp#password")
        node: the IncludeNode (has .context, .optional, etc.)
        draconloader: the current DraconLoader instance

    Returns:
        tuple of (content_string, context_dict)
        - content_string: YAML string to parse, or a CompositionResult
        - context_dict: extra context variables to inject (e.g., FILE_PATH)
    """
    content = fetch_from_somewhere(path)
    return content, {'SOURCE': f'my_loader:{path}'}
```

### Registering

Pass `custom_loaders` to the `DraconLoader`:

```python
import dracon

loader = dracon.DraconLoader(
    custom_loaders={'vault': vault_loader}
)
config = loader.load('config.yaml')
```

This adds your loader alongside the built-in ones (`file`, `pkg`, `env`, `var`, `raw`, `rawpkg`, `cascade`).

### Example: HashiCorp Vault loader

```python
import hvac

def vault_loader(path, node=None, draconloader=None):
    """Fetch secrets from HashiCorp Vault.

    Usage in YAML: !include vault:secret/data/myapp#password
    """
    # split path and key
    if '#' in path:
        vault_path, key = path.rsplit('#', 1)
    else:
        vault_path, key = path, None

    client = hvac.Client()
    response = client.secrets.kv.v2.read_secret_version(path=vault_path)
    data = response['data']['data']

    if key:
        # return a single value as a YAML scalar
        return str(data[key]), {}
    else:
        # return the whole secret as YAML
        import yaml
        return yaml.dump(data), {}

# register it
loader = dracon.DraconLoader(
    custom_loaders={'vault': vault_loader}
)
```

### Using it

```yaml
database:
  host: db.example.com
  password: !include vault:secret/data/myapp#password
```

### Returning a CompositionResult

For more control, your loader can return a `CompositionResult` directly instead of a string. This skips the YAML parsing step:

```python
from dracon.composer import CompositionResult
from dracon.nodes import DraconScalarNode

def my_loader(path, node=None, draconloader=None):
    value = compute_value(path)
    scalar = DraconScalarNode(tag='tag:yaml.org,2002:str', value=str(value))
    return CompositionResult(root=scalar), {}
```

The built-in loaders all follow this same interface, so you can look at `dracon/loaders/` for more examples.

## Custom resolution sources

Tag resolution (`!MyType`) and reverse identification (`identify(value) -> tag_name`) both flow through one `SymbolTable` on the loader. The table consults an ordered chain of `SymbolSource` records on miss — by default `[builtin, user_vocab, dynamic_import]`, where `dynamic_import` is the `importlib.import_module` fallback that has always been there. Registering a custom source is the supported way to add a *new* tag-resolution behavior without subclassing `Draconstructor`.

A plugin registry is a typical use case:

```python
from dracon import (
    DraconLoader, SymbolSource, SymbolEntry, SymbolTable,
    CallableSymbol, make_dynamic_import_source,
)

# build an explicit registry of plugin types
plugin_table = SymbolTable()
for name, cls in my_plugin_registry.items():
    plugin_table.define(SymbolEntry(name=name, symbol=CallableSymbol(cls, name=name)))

plugin_source = SymbolSource(
    name="plugin_registry",
    lookup=plugin_table.__getitem__,
    identify=plugin_table.identify,
    canonical_for_identify=True,  # this source can answer reverse identify()
)

# put plugins ahead of dynamic-import fallback
loader = DraconLoader(symbol_sources=[plugin_source, make_dynamic_import_source()])

cfg = loader.loads("worker: !MyPlugin { mode: fast }")  # !MyPlugin resolved by source
```

Sources can be reordered, replaced, or *omitted* entirely. For a sandboxed runtime (Pyodide preview, untrusted-agent vocabulary) leave out `make_dynamic_import_source()` — the loader then refuses any tag that isn't in the explicit chain instead of silently importing it. See [Loader API → Trust zones](../reference/loader-api.md#trust-zones-via-symbol_sources) for the full pattern.
