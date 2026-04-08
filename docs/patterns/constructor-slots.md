# Pattern: Constructor Slots

## The problem

You want the config to choose what gets constructed.

Different model classes. Different task types. Different endpoint builders. Different backends.

The usual alternatives are all a bit annoying:

- `_target_`-style strings
- `!if` ladders
- Python `if/elif` dispatch
- a pile of duplicated blocks that differ only by the constructor

Dracon can do this more directly.

## The pattern

Store constructors in config scope, then select them with a dynamic tag.

```yaml
!define model_types:
  resnet: ResNet
  transformer: Transformer

!set_default model_kind: resnet

model: !$(model_types[model_kind])
  layers: 12
```

If `model_kind` is `resnet`, this behaves like:

```yaml
model: !ResNet
  layers: 12
```

If `model_kind` is `transformer`, the tag resolves to `!Transformer` instead.

That means the body stays normal YAML. Only the constructor slot is dynamic.

## Why this is nice

The object body stays declarative.

Compare this:

```yaml
model: !$(model_types[model_kind])
  layers: 12
```

to the more expression-heavy alternative:

```yaml
model: ${model_types[model_kind](layers=12)}
```

Both work. The dynamic-tag version is easier to read once the body is more than one or two fields.

## CLI selection

This pattern is especially useful with CLI overrides:

```yaml
!define model_types:
  resnet: ResNet
  transformer: Transformer

!set_default model_kind: resnet
```

Now:

```bash
++model_kind=transformer
```

switches the constructor cleanly.

The important detail is that the CLI is selecting a symbolic key like `transformer`, not trying to inject a raw Python symbol.

## Aliasing the chosen constructor

If you want to reuse the selected constructor several times, alias it once:

```yaml
!define model_types:
  mlp: MLP
  transformer: Transformer

!set_default model_kind: mlp

!define Net: ${model_types[model_kind]}

encoder: !Net { hidden: 256 }
decoder: !Net { hidden: 128 }
```

That keeps the rest of the file stable even if the slot logic changes.

## It works for callables too

Constructor slots are not limited to Python types.

The same dynamic-tag pattern works for callable builders:

```yaml
!define endpoint_factories:
  http: make_http_endpoint
  grpc: make_grpc_endpoint

!set_default transport: http

service: !$(endpoint_factories[transport])
  name: api
  port: 443
```

That gives you swappable construction behavior without writing a dispatch function in Python.

## Good use cases

- selecting model classes
- selecting task or job schemas
- choosing transport-specific builders
- switching between implementations in tests vs production
- parameterizing reusable vocabularies

## Related pages

- [The Open Vocabulary](../concepts/open-vocabulary.md)
- [Layered Vocabularies](layered-vocabularies.md)
- [Hybrid Pipelines](hybrid-pipelines.md)
