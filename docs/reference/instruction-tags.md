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

`!include`, `!deferred`, `!raw`, `!noconstruct`, and `!unset` are handled by the composition pipeline directly, not by the instruction registry.

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
- A `!fn` callable -- stored as a `CallableSymbol` of kind `'template'`
- A `!pipe` pipeline -- stored as a `CallableSymbol` of kind `'pipe'`
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

Also supports typed coercion for primitives: `!set_default:int`, `!define?:float`, etc.

For arbitrary type names (resolved through the active scope), the `:Type`
suffix records type metadata on the surrounding template's `InterfaceSpec`
without coercing the value:

```yaml
!define mk: !fn
  !set_default:Gate gate: "default-gate"
  ok: 1
```

The `Gate` annotation surfaces in `mk.interface().params[0].annotation_name`
(and as the resolved type in `.annotation` when `Gate` is in scope).

### Mapping body (CLI metadata)

A top-level `!set_default` can carry CLI metadata via a mapping body. When the
config is loaded by a `@dracon_program` CLI, these directives surface as real
argparse flags — `--name value`, `--help`-visible, with optional short alias.

```yaml
!set_default:int workers:
  default: 4
  help: "worker count"
  short: -w
```

Allowed body keys for `!set_default`: `default`, `help`, `short`, `hidden`.

| key       | type            | meaning                                                  |
|-----------|-----------------|----------------------------------------------------------|
| `default` | any             | the default value (coerced to `:Type` if typed)          |
| `help`    | str             | help text shown in `--help`                              |
| `short`   | str (`-x`)      | short alias (single char, must not collide with model)   |
| `hidden`  | bool            | omit from `--help`                                       |

The scalar form (`!set_default workers: 4`) is still valid: it is sugar for
`{default: 4}` with no CLI metadata. Inner-scope directives (inside `!fn`,
`!deferred`, or `!if` branches) are not exposed as CLI flags — they remain
contracts of the template they belong to.

See [CLI flags from config layers](cli-api.md#cli-flags-from-config-layers)
for the precedence rules and the `++` fallback.

---

## !require

Declares that a variable must be provided by some outer scope (a `!define`, a `!set_default`, CLI `++`, CLI `--flag`, or programmatic context). Checked after all instructions have run.

```yaml
!require api_key: "API key needed. Set via ++api_key=... or --api-key"
```

If the variable is not satisfied by end of composition, raises `CompositionError` with the hint message. Removed from the tree (pure validation).

### Mapping body (CLI metadata)

A top-level `!require` can carry CLI metadata to surface as a real argparse
flag in `@dracon_program` CLIs. The same grammar as `!set_default`, minus
`default` (a required variable has no default by definition):

```yaml
!require port:
  help: "bind port"
  short: -p
```

Allowed body keys for `!require`: `help`, `short`, `hidden`. Passing
`default` raises a `CompositionError`.

### Typed `!require:Type`

Add a type-annotation suffix to record the parameter's type on the
surrounding template's `InterfaceSpec`:

```yaml
!define MakePlot: !fn
  !require:list[Event] events: "events to plot"
  !require:Gate gate: "active gate"
  !returns:PlotData _:
  kind: derive
```

The annotation is metadata only — Dracon does not perform runtime type
checking beyond what construction or callable invocation already does.
`Type` is resolved through the active scope (just like a tag), so a class
made visible by `!include vocab.yaml` or by `context_types=[...]` becomes
the live `annotation` on the param. Strings that don't resolve stay in
`annotation_name` for documentation and JSON output. Untyped `!require`
remains valid.

---

## !returns

Pure metadata marker for `!fn` and `!deferred` bodies that records the
return type on the symbol's `InterfaceSpec`. Removed from the final tree.

```yaml
!define mk: !fn
  !returns:PlotData _:
  !fn :
    rows: 3
```

Two YAML-friendly forms are accepted: `!returns:Type _:` (type in the tag,
empty key) and `!returns _: Type` (type in the value). Both produce the
same `return_annotation_name` on the resulting `InterfaceSpec`.

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

Creates a `CallableSymbol` of kind `'partial'` -- a partial application of a Python callable with pre-filled kwargs.

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

Nested pipe instances are flattened automatically.

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

## !raw

Mark a scalar value as opaque to all Dracon phases. The string is carried through composition, construction, and lazy resolution without any interpretation. Downstream systems (runtimes, template engines, shells) can evaluate the contents however they like.

```yaml
env:
  HUNT_KNOWN_BUGS: !raw "channels.messages('known_bugs')"
  SHELL_HOME: !raw "${HOME}/.config"
```

`!raw` is the scalar dual of `!deferred`:

- `!deferred` pauses a **subtree** for later construction by Dracon
- `!raw` marks a **scalar** that Dracon will never evaluate

The phase boundary is on the value, not the template. A `!raw` value flows through `!fn` invocations untouched:

```yaml
!define make_job: !fn
  !require cmd: "command expression"
  !fn :
    run: ${cmd}

job: !make_job
  cmd: !raw "runtime.dispatch('task')"
# job.run is a RawExpression, not an interpolated string
```

### When to use `!raw` vs escaping

Use `!raw` when a value is meant for a different evaluator entirely. Use `$${}` escaping when you just need a literal `${...}` in the output. The key difference: `!raw` survives any number of `!fn` nesting levels without counting escape layers.

### Python type

`RawExpression` is a `str` subclass. It works anywhere a string does and round-trips through `dump`/`loads` preserving the `!raw` tag.

```python
from dracon import RawExpression

expr = RawExpression("channels.messages('bugs')")
isinstance(expr, str)  # True
```

In Pydantic models, type the field as `RawExpression | str` to accept both regular strings and raw expressions.

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
