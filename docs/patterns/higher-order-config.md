# Pattern: Higher-Order Config

## The problem

Sometimes you do not want the config to build the final object directly.

You want it to build a configured callable:

- a loss function with stored kwargs
- a transform
- a callback factory
- a request wrapper
- a reusable stage that another pipeline can call later

That is one level more abstract than an ordinary template.

## The pattern

Use `!fn` to return another callable, usually a `!fn:path` partial.

```yaml
!define make_greeter: !fn
  !require greeting: "greeting"
  !fn : !fn:greet
    greeting: ${greeting}

casual: !make_greeter { greeting: hey }
formal: !make_greeter { greeting: hello }
```

If `greet` is a Python callable in the loader context, then `casual` and `formal` become configured `DraconPartial` objects.

From Python:

```python
casual("world")   # "hey world"
formal("team")    # "hello team"
```

## Why this is interesting

This is config producing executable configured objects, not just plain data.

The first `!fn` is a template that runs during composition. The value it returns is another callable object that can be stored, serialized, passed around, and invoked later.

That is why this deserves its own pattern name. It is higher-order in the same sense that a Python function returning another function is higher-order.

## Why use this instead of a Python factory

Because the factory itself becomes configurable.

You can:

- select which configured callable to build
- sweep over families of configured callables
- keep the configuration of those callables in YAML
- dump and inspect the resulting partials

This is especially useful when the "thing you want to build later" is still part of the experiment or app configuration.

## Common cases

- configured loss functions
- data transforms
- notification or logging callbacks
- reusable service clients
- preconfigured stages for `!pipe`

## A practical guideline

If a config subtree should eventually be called like a function, consider whether the right output is a `!fn:path` partial rather than a fully constructed object.

That usually keeps the boundary cleaner.

## Related pages

- [YAML Functions](../guides/yaml-functions.md)
- [Hybrid Pipelines](hybrid-pipelines.md)
- [The Open Vocabulary](../concepts/open-vocabulary.md)
