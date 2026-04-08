# The Open Vocabulary

One of the easier ways to misunderstand Dracon is to think of context as just a bag of variables.

It is more useful to think of it as an open vocabulary -- a typed symbol table where values, constructors, and callables all live in one namespace.

## One namespace, several kinds of things

A name in Dracon scope can refer to:

- a plain value
- a Python type
- a Python callable
- a YAML template created with `!fn`
- a configured Python callable created with `!fn:path`
- a pipeline created with `!pipe`

From the caller's point of view, these often feel close enough that you can:

- select them from a mapping
- alias them with `!define`
- pass them through another template
- expose them as part of a vocabulary file
- invoke them with tag syntax

That is a big part of where Dracon's composability comes from.

## The runtime model

Under the hood, every name in scope is backed by a **symbol** with a consistent interface:

- `interface()` -- what kind of symbol it is, what parameters it expects, what contracts it has
- `bind(**kwargs)` -- partially apply arguments
- `invoke(**kwargs)` -- call it
- `materialize()` -- get the raw value

This means the system doesn't need separate codepaths for "is it a type? a callable? a template?". One model handles all of them.

The `InterfaceSpec` that each symbol exposes is the single source of truth for:

- tag invocation and parameter validation
- pipe threading (which params to fill automatically)
- error messages (showing what was expected vs what was provided)
- the `--symbols` CLI output
- the `__scope__` introspection API

## The same name can be used in different ways

A value can be used in expressions:

```yaml
region: ${default_region}
```

A type can be used as a tag:

```yaml
model: !ResNet
  layers: 12
```

A callable can also be used as a tag:

```yaml
endpoint: !Service { name: api, port: 443 }
```

A pipeline can be invoked from an expression:

```yaml
report: ${train_pipeline(source='s3://raw')}
```

And with dynamic tags, the tag itself can be selected from config:

```yaml
item: !$(constructors[kind])
  name: thing
```

That last move is especially important. It means the config can choose not just values, but constructors and builders.

And if the expression is more complex, you can alias it into a normal tag first:

```yaml
!define Builder: ${constructors[kind]}

item: !Builder
  name: thing
```

That sounds small, but it matters a lot in practice. The tag stays short, and the selection logic gets a name.

## Self-documenting configs with `__scope__`

Since the symbol table is a first-class runtime object, configs can describe their own vocabulary:

```yaml
!include infra_vocab.yaml
!include ml_vocab.yaml

_vocabulary:
  types: ${__scope__.names(kind='type')}
  templates: ${__scope__.names(kind='template')}
```

You can also use it for guards and introspection:

```yaml
!assert ${__scope__.has('Service')}: "infra vocabulary not loaded"
model_interface: ${__scope__.interface('Experiment')}
```

The `__scope__` object exposes:

| Method | Returns | Purpose |
|--------|---------|---------|
| `names(kind=None)` | `list[str]` | symbol names, optionally filtered by kind |
| `interface(name)` | `InterfaceSpec` | full interface for a symbol |
| `has(name)` | `bool` | check if a symbol exists in scope |
| `kinds()` | `dict[str, SymbolKind]` | name-to-kind mapping |
| `exported()` | `SymbolTable` | sub-table of exported entries only |

This is pure SSOT -- the documentation comes from the same runtime model that drives execution.

## Why the caller often does not care what a name "really is"

From the outside, these can all behave like reusable named operations:

- a type constructs an object
- a `!fn` template constructs a mapping or scalar
- a `!fn:path` partial calls a Python function with stored kwargs
- a `!pipe` runs a workflow

The user often only cares that:

- the name exists
- it accepts certain inputs
- it produces the expected output

That is why pattern pages like [Constructor Slots](../patterns/constructor-slots.md), [Layered Vocabularies](../patterns/layered-vocabularies.md), and [Hybrid Pipelines](../patterns/hybrid-pipelines.md) fit together so naturally. They are all different uses of the same open-vocabulary idea.

## Dynamic tags

Dynamic tags are the cleanest expression of this model:

```yaml
!define model_types:
  resnet: ResNet
  transformer: Transformer

!set_default model_kind: resnet

model: !$(model_types[model_kind])
  layers: 12
```

The body stays normal YAML. The vocabulary slot is what changes.

For short cases, the slot does not need to come from a mapping at all:

```yaml
!set_default tag_value: ResNet

model: !$(tag_value)
  layers: 12
```

That works when the slot resolves to a symbolic tag name directly.

This works for:

- Python types
- `!fn` templates
- plain Python callables

When the expression inside `!$(...)` stops being simple, alias it first:

```yaml
!define Action: ${llm_decide(prompt='triage', metrics=jobs.meta(group='trials'))}

do: !Action {}
```

This is usually clearer than trying to cram a long expression directly into a tag, and it avoids awkward YAML-tag syntax when the expression contains spaces.

The alias form is also the right one when your selection resolves to an actual Python type or callable object instead of a plain tag-name string:

```yaml
!define Tag: ${ResNet}

model: !Tag
  layers: 12
```

## A note on CLI values

When the CLI injects a value with `++name=value`, it is injecting data, not a Python symbol lookup.

So the robust pattern is:

```yaml
!define model_types:
  resnet: ResNet
  transformer: Transformer

!set_default model_kind: resnet
```

then override `model_kind`, not the raw constructor name itself.

That keeps the public interface stable and explicit.

## Why this matters

This is the conceptual glue behind a lot of Dracon's more powerful patterns.

Without this model, the system can look like a bag of separate features:

- interpolation
- custom tags
- `!fn`
- `!pipe`
- propagated vocabularies

With the symbol model, they line up:

Dracon gives you a namespace where values, constructors, and callables are all typed symbols that can be named, selected, introspected, and composed.

## Related pages

- [Context and Scope](context-and-scope.md)
- [The Primitives](primitives.md)
- [Constructor Slots](../patterns/constructor-slots.md)
- [Layered Vocabularies](../patterns/layered-vocabularies.md)
- [Hybrid Pipelines](../patterns/hybrid-pipelines.md)
- [Debugging](../guides/debugging.md)
