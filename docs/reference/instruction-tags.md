# Instruction Tags

All instruction tags recognized during composition. Tags are processed on YAML mapping keys and removed from the final tree (unless noted otherwise).

---

## Processing Order

1. `!set_default` / `!define?` -- soft variable definitions
2. `!define` -- hard variable definitions
3. `!each` -- loop expansion
4. `!if` -- conditional inclusion

After all instructions:

5. `!require` -- checked for unsatisfied requirements
6. `!assert` -- evaluated in a separate pass

`!include`, `!deferred`, `!noconstruct`, and `!unset` are handled by the composition pipeline directly, not by the instruction registry.

---

## !define

Define a variable and add it to the context of sibling and descendant nodes. The definition node is removed from the tree.

```yaml
!define base_url: "https://api.example.com"

endpoint: "${base_url}/users"
```

The value can be:

- A scalar (string, number, bool)
- An interpolation expression (`${...}`) -- evaluated at composition time
- A mapping or sequence -- constructed immediately
- A `!fn` callable -- stored as a `DraconCallable`
- A `!pipe` pipeline -- stored as a `DraconPipe`
- A tagged mapping (e.g. `!MyModel`) -- lazily constructed as `LazyConstructable`

Variable names must be valid Python identifiers.

### !define:type

Coerce the value to a specific type after evaluation.

```yaml
!define:int port: "8080"
!define:float rate: "0.5"
```

Supported types: `int`, `float`, `str`, `bool`, `list`, `dict`.

---

## !set_default / !define?

Soft definition. Sets the variable only if it does not already exist in the context. Values from `!define` or CLI `++` override soft defaults.

```yaml
!set_default env: "development"
# or equivalently:
!define? env: "development"
```

Also supports typed coercion: `!set_default:int`, `!define?:float`, etc.

---

## !require

Declares that a variable must be provided by some outer scope (a `!define`, a `!set_default`, CLI `++`, or programmatic context). Checked after all instructions have run.

```yaml
!require api_key: "API key needed. Set via ++api_key=..."
```

If the variable is not satisfied by end of composition, raises `CompositionError` with the hint message. Removed from the tree (pure validation).

---

## !assert

Validate an invariant on the composed tree. Evaluated after all other instructions.

```yaml
!assert ${port > 0 and port < 65536}: "port must be between 1 and 65535"
```

The key must be an interpolation expression that evaluates to a truthy/falsy value. If falsy, raises `CompositionError` with the message. Removed from the tree.

---

## !if

Conditional inclusion. The key is an expression evaluated for truthiness.

### Shorthand form

Include the content if the condition is true, otherwise remove the node entirely:

```yaml
!if ${enable_debug}:
  log_level: DEBUG
  log_file: debug.log
```

### Then/else form

```yaml
!if ${env == 'production'}:
  then:
    log_level: WARNING
  else:
    log_level: DEBUG
```

If the `else` key is absent and the condition is false, the node is removed.

The condition value can be a plain scalar (`true`/`false`/`0`/`1`) or an interpolation.

---

## !each

Loop expansion. Duplicates the template body for each item in a list-like expression.

```yaml
!each(name) ${['alice', 'bob', 'charlie']}:
  user_${name}:
    email: "${name}@example.com"
```

The variable (`name` in this example) is available in `${...}` expressions inside the template.

### Sequence value (generates list items)

```yaml
items:
  !each(i) ${range(3)}:
    - "item_${i}"
# result: items: [item_0, item_1, item_2]
```

When all keys in a mapping are `!each` instructions with sequence values, they are expanded and spliced into the parent sequence.

### Key expression

The key must be an interpolation expression that evaluates to an iterable. Plain scalars are not valid.

### Nested instructions

`!each` can contain other instructions (`!define`, `!if`, etc.) in its body. They are expanded per-iteration.

---

## !fn

Define a callable YAML template. Three forms:

### File reference

```yaml
!define processor: !fn file:processor.yaml
```

Loads the file as a template. Each call deepcopies the template, injects kwargs as context, and runs composition + construction.

### Inline mapping

```yaml
!define greeting: !fn
  !require name: "name is required"
  !set_default greeting: "Hello"
  message: "${greeting}, ${name}!"
```

The `!fn` tag goes on the value node, not as a separate key. The mapping body becomes the template. Use `!require` for mandatory parameters and `!set_default` for optional ones.

### Expression lambda

```yaml
!define double: !fn ${x * 2}
```

The value is an interpolation expression. Parameters come from the caller's kwargs.

### Return marker (`!fn :`)

Inside a mapping template body, tagging a key with `!fn` marks it as the return value. The callable returns only that value instead of the whole mapping.

```yaml
!define compute: !fn
  !require x: "input"
  intermediate: ${x * 2}
  !fn : ${intermediate + 1}
# compute(x=5) returns 11, not the whole mapping
```

### Invocation

Callables defined by `!fn` are invoked via `${fn_name(key=value)}` in expressions or programmatically as regular Python callables.

---

## !fn:path (Partial Application)

Creates a `DraconPartial` -- a partial application of a Python callable with pre-filled kwargs.

```yaml
!define my_loader: !fn:mymodule.load_data
  format: csv
  encoding: utf-8
```

The dotted path is resolved as a Python import. The mapping body provides default kwargs. At call time, runtime kwargs override the defaults.

If the path has no dots, it is looked up in the current context instead of imported.

---

## !pipe

Function composition. Chains a sequence of callables where each stage's output feeds into the next.

```yaml
!define pipeline: !pipe
  - load_data
  - clean_data:
      remove_nulls: true
  - ${custom_transform}
  - !fn:mymodule.save
      path: output.csv
```

### Stage types

- **Bare name**: resolved from context
- **Name with kwargs**: `name: {kwargs}` -- pre-fills kwargs for that stage
- **Interpolation**: `${expr}` -- resolved at definition time
- **Tagged node**: `!fn:path {kwargs}` -- constructed via the loader

### Value threading

- If a stage returns a mapping, it is unpacked as `**kwargs` into the next stage
- If a stage returns a non-mapping, it is passed as the single unfilled `!require` parameter of the next stage

Nested `DraconPipe` instances are flattened automatically.

---

## !include

Include content from an external source. See [Include Schemes](include-schemes.md) for the full list of schemes.

```yaml
database: !include file:db.yaml
settings: !include pkg:mypackage:defaults.yaml
api_key: !include env:API_KEY
```

### Selector

Append `@keypath` to extract a subtree:

```yaml
db_host: !include file:config.yaml@database.host
```

### Internal references

- Absolute path: `!include /some.path` -- reference within the current document
- Relative path: `!include .sibling` or `!include ..parent.key`
- Anchor: `!include anchor_name` or `!include anchor_name.sub.key`

---

## !include?

Optional include. If the source is not found (e.g. missing file), the node is silently removed instead of raising `FileNotFoundError`.

```yaml
overrides: !include? file:local-overrides.yaml
```

---

## !deferred

Pause composition at this node. The subtree is wrapped in a `DeferredNode` and not processed further until explicitly composed/constructed at runtime.

```yaml
template: !deferred
  greeting: "Hello, ${name}!"
```

### Extended syntax

#### `!deferred:Type`

Specify the target type for construction:

```yaml
model: !deferred:MyModel
  field1: value
```

#### `!deferred::query_params`

Query-string style parameters:

```yaml
model: !deferred::clear_ctx=true:MyModel
  field1: value
```

- `clear_ctx=true` -- clear the inherited context before constructing
- `reroot=true` -- re-root the composition at this node

#### `!deferred::query:Type`

Combine query params and a type:

```yaml
config: !deferred::reroot=true:ServerConfig
  host: localhost
```

---

## !noconstruct

When used as a tag on a mapping key, `!noconstruct` causes the entire key-value pair to be skipped during construction. The pair does not appear in the constructed output at all.

```yaml
!noconstruct raw_template:
  key: ${expr}  # this entire entry is removed from the constructed output
```

---

## !unset

Mark a key for deletion during merge processing. Used to remove inherited keys.

```yaml
<<: !include file:base.yaml
unwanted_key: !unset
```

After merges are processed, any key with `!unset` as its value is deleted from the parent mapping.

---

## Custom Instructions

Register your own instruction tags:

```python
from dracon import register_instruction, Instruction

class MyInstruction(Instruction):
    @staticmethod
    def match(value):
        if value == '!mytag':
            return MyInstruction()
        return None

    def process(self, comp_res, path, loader):
        # modify comp_res and return it
        return comp_res

register_instruction('!mytag', MyInstruction)
```
