# Pattern: Weighted Registries

## The problem

You have a lot of config variants that are almost the same.

Typical examples:

- dataset collections
- feature bundles
- loss-term stacks
- experiment menus
- evaluation suites

The naive version is one file per variant:

- `full.yaml`
- `no_noise_floor.yaml`
- `cascades_only.yaml`
- `uorfs_only.yaml`
- `paper_subset.yaml`

That gets messy fast. Most files are copies of the same list with one or two items changed.

Then the day you add one new dataset, feature, or loss term, you have to remember to update a pile of variants.

## The pattern

Write the full list once, in one registry file.

Give each item a default weight. Then other files do not rewrite the list. They only override the few weights that should change.

In other words:

- one file says what exists
- smaller files say what to turn down, turn up, or turn off

## A dataset-flavored example

Put the full menu in one place:

```yaml
# datasets/_registry.yaml
!set_default:float weight_genomics: 1.0
!set_default:float weight_cascades: 1.0
!set_default:float weight_noise_floor: 0.25

sets:
  genomics:
    !if ${weight_genomics > 0}:
      then: !NetworkSet
        content:
          - experiment_name: 2024-12-01_genomics
      else: !NetworkSet
        content: []

  cascades:
    !if ${weight_cascades > 0}:
      then: !NetworkSet
        content:
          - experiment_name: 2024-12-01_cascades
      else: !NetworkSet
        content: []

  noise_floor:
    !if ${weight_noise_floor > 0}:
      then: !NetworkSet
        content:
          - experiment_name: 2024-12-01_noise_floor
      else: !NetworkSet
        content: []
```

That file is the master list.

## Variants become small override files

The full set is just the registry:

```yaml
# datasets/sets/full.yaml
<<: !include file:$DIR/../_registry.yaml
```

Another set only overrides what changes:

```yaml
# datasets/sets/cascades_only.yaml
<<: !include file:$DIR/full.yaml

!define weight_genomics: 0.0
!define weight_noise_floor: 0.0
```

Another variant can keep everything but make one item weaker:

```yaml
# datasets/sets/light_noise.yaml
<<: !include file:$DIR/full.yaml

!define weight_noise_floor: 0.05
```

The nice part is that these files are tiny. They only mention what is different.

## Why this works well

Instead of "many mostly-copied lists", you get:

- one master list
- a few small override files

That has a few practical benefits:

- adding a new item happens in one place
- old variants pick it up automatically unless they explicitly opt out
- variant files are easier to read because they only mention what changed
- CLI overrides become much more useful

## CLI ergonomics

Once the registry exposes weights through `!set_default`, a one-off run often does not need its own file at all:

```bash
++weight_noise_floor=0.0
++weight_genomics=0.5
```

That is often enough to replace dozens of historical “just for this run” configs.

## The key idea

Keep two things separate:

- the full list of available items
- the choice of which items are active for this run

Once those stop being mixed together, the config tree usually gets much smaller.

## Good use cases

- dataset menus with optional subsets
- loss stacks where terms can be weakened or disabled
- evaluation suites with optional checks
- feature registries where some features are experimental
- job menus where some jobs are active only in certain runs

## When not to use it

If each variant has genuinely different structure, this pattern is the wrong abstraction.

Weighted registries are best when the available items stay mostly stable, and the variants mostly differ by:

- inclusion
- exclusion
- weights
- a few small per-member overrides

## Related pages

- [Config Templates](config-templates.md)
- [Dynamic Skeleton](dynamic-skeleton.md)
- [Sweep Generation](sweep-generation.md)
