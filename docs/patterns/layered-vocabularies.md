# Pattern: Layered Vocabularies

## The problem

One reusable template is nice. A reusable config language is better.

Once a project grows a bit, you usually want more than isolated snippets:

- infrastructure-level building blocks
- domain-level templates on top of those blocks
- project-specific tags on top of that

If every layer has to drop back to Python glue, the YAML side stops feeling like a real language.

## The pattern

Use `<<(<):` to propagate definitions upward, and let vocabulary files build on earlier vocabulary files.

### Layer 1: infrastructure vocabulary

```yaml
# infra.yaml
!define Service: !fn
  !require name: "service name"
  !set_default port: 8080
  !fn :
    url: "https://${name}.internal:${port}"
    health: "https://${name}.internal:${port}/health"
```

### Layer 2: domain vocabulary

```yaml
# ml.yaml
<<(<): !include file:infra.yaml

!define Experiment: !fn
  !require name: "experiment"
  !fn :
    api: !Service { name: "${name}-api", port: 443 }
    dashboard: !Service { name: "${name}-dash" }
```

### User config

```yaml
<<(<): !include file:ml.yaml

run: !Experiment { name: genomics-v2 }
```

The caller only needs to know `!Experiment`. The lower-level `!Service` machinery is still there, but it has been wrapped into a better abstraction.

## What `(<)` is doing

Without `(<)`, the imported file still contributes concrete keys when merged, but its `!define` variables stay local to that include.

With `(<)`, definitions propagate into the parent scope. That is why:

- the top-level config can see `!Experiment`
- `ml.yaml` can see `!Service`

This is the piece that turns vocabulary files into composable layers instead of isolated snippets.

## Why this pattern matters

This is where Dracon starts behaving less like "templated YAML" and more like a small config language.

You can build a stack like:

- infrastructure vocabulary
- ML vocabulary
- project vocabulary
- local experiment config

Each layer exposes a cleaner interface than the one below it.

## A small extension

Vocabulary layers do not have to export only callables. They can also export constants, defaults, and helper constructors:

```yaml
!define default_region: us-east-1
!define artifact_root: /mnt/artifacts
```

Those become part of the same shared vocabulary.

## When to use this

- shared config libraries inside a package
- domain-specific config DSLs
- large projects with repeated infrastructure concepts
- cases where you want users to interact with higher-level tags instead of low-level plumbing

## When not to use it

If you only need one reusable template in one file, plain `!fn` is simpler.

Layered vocabularies are worth it when you want a real public surface:

- reusable tags
- reusable defaults
- reusable config conventions

## Related pages

- [Config Templates](config-templates.md)
- [The Merge Operator](../concepts/merge-algebra.md)
- [The Open Vocabulary](../concepts/open-vocabulary.md)
