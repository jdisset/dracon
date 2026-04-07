# Pattern: Sweep Generation

## The problem

You need to run the same program with many different parameter combinations. Hyperparameter search, multi-environment testing, benchmark matrices. Writing each combination by hand is tedious and error-prone. You want the config system to generate the combinations for you.

Dracon's `!each`, `!if`, and `${...}` expressions handle the generation side. You write the structure once, specify the axes, and get the full grid (or a filtered subset) as output.

## 1. Grid sweep with !each

The basic pattern: nest `!each` loops over your parameter axes.

```yaml
# sweep.yaml

!define learning_rates: [0.001, 0.01, 0.1]
!define batch_sizes: [32, 64, 128]

jobs:
  !each(lr) ${learning_rates}:
    !each(bs) ${batch_sizes}:
      - name: "lr${lr}_bs${bs}"
        learning_rate: ${lr}
        batch_size: ${bs}
        epochs: 100
        output_dir: "/results/lr${lr}_bs${bs}"
```

Result (9 jobs):

```yaml
jobs:
  - name: lr0.001_bs32
    learning_rate: 0.001
    batch_size: 32
    epochs: 100
    output_dir: /results/lr0.001_bs32
  - name: lr0.001_bs64
    learning_rate: 0.001
    batch_size: 64
    epochs: 100
    output_dir: /results/lr0.001_bs64
  # ... 7 more
```

The outer `!each` iterates over learning rates. For each one, the inner `!each` iterates over batch sizes. The body is duplicated for every combination. Items from the inner loop are spliced inline into the parent list.

## 2. Conditional sweep with !each + !if

Some combinations don't make sense. Large batch sizes with very low learning rates might be wasteful. Use `!if` inside the loop body to skip them.

```yaml
!define learning_rates: [0.001, 0.01, 0.1]
!define batch_sizes: [32, 64, 128, 256]

jobs:
  !each(lr) ${learning_rates}:
    !each(bs) ${batch_sizes}:
      !if ${not (bs >= 128 and lr <= 0.001)}:
        - name: "lr${lr}_bs${bs}"
          learning_rate: ${lr}
          batch_size: ${bs}
```

When the condition is false, the block produces nothing and that combination is omitted from the output. This is a simple way to prune the search space without writing custom scripts.

You can also use `!if` for conditional settings within each job:

```yaml
jobs:
  !each(lr) ${learning_rates}:
    !each(bs) ${batch_sizes}:
      - name: "lr${lr}_bs${bs}"
        learning_rate: ${lr}
        batch_size: ${bs}
        !if ${bs >= 128}:
          gradient_accumulation: ${256 // bs}
        !if ${lr >= 0.1}:
          warmup_steps: 1000
```

## 3. Expression-based sweeps

When your parameter values aren't a fixed list, use `${...}` expressions to compute them.

### Log-spaced learning rates

```yaml
!define lrs: ${[round(10**x, 6) for x in [-4, -3.5, -3, -2.5, -2, -1.5, -1]]}

jobs:
  !each(lr) ${lrs}:
    - learning_rate: ${lr}
      name: "lr_${lr}"
```

### Random sampling

```yaml
!define random_lrs: ${[round(10**random.uniform(-4, -1), 6) for _ in range(20)]}

jobs:
  !each(lr) ${random_lrs}:
    - learning_rate: ${lr}
      batch_size: 64
      name: "random_lr_${lr}"
```

`random` is available in expressions by default (it's part of Python's standard library, imported automatically by the expression engine).

### Combinations from structured data

```yaml
!define models:
  - { name: resnet50, lr: 0.01 }
  - { name: vit_base, lr: 0.001 }
  - { name: efficientnet, lr: 0.005 }

!define datasets: [imagenet, cifar100, flowers102]

jobs:
  !each(m) ${models}:
    !each(d) ${datasets}:
      - model: ${m['name']}
        dataset: ${d}
        learning_rate: ${m['lr']}
        output: "/results/${m['name']}/${d}"
```

Each model carries its own preferred learning rate. The sweep iterates over models and datasets, using model-specific values where needed.

## 4. Dynamic config groups

When your parameter variations are full config files rather than simple values, use `!each` with `listdir` to iterate over a directory of configs.

```yaml
# sweep_from_files.yaml

experiments:
  !each(f) ${[x for x in listdir($DIR + '/configs') if x.endswith('.yaml')]}:
    ${f.replace('.yaml', '')}: !include file:$DIR/configs/${f}
```

If `configs/` contains `small.yaml`, `medium.yaml`, `large.yaml`, the result is:

```yaml
experiments:
  small:
    # ... contents of configs/small.yaml
  medium:
    # ... contents of configs/medium.yaml
  large:
    # ... contents of configs/large.yaml
```

You can combine this with a template to layer shared settings over each config:

```yaml
!define base_settings:
  epochs: 100
  optimizer: adam
  output_root: /results

experiments:
  !each(f) ${[x for x in listdir($DIR + '/configs') if x.endswith('.yaml')]}:
    ${f.replace('.yaml', '')}:
      <<: ${base_settings}
      <<{<+}: !include file:$DIR/configs/${f}
```

## 5. Sweep with !fn templates

For cleaner sweep definitions, combine `!fn` with `!each`:

```yaml
!define make_job: !fn
  !require model: "model name"
  !require lr: "learning rate"
  !set_default epochs: 100
  !set_default bs: 64
  name: "${model}_lr${lr}_bs${bs}"
  model: ${model}
  learning_rate: ${lr}
  batch_size: ${bs}
  epochs: ${epochs}

!define configs:
  - { model: resnet, lr: 0.01 }
  - { model: vit, lr: 0.001, epochs: 200 }
  - { model: mlp, lr: 0.1, bs: 128 }

jobs:
  !each(c) ${configs}:
    - ${make_job(**c)}
```

The `**c` unpacks each dict as keyword arguments to the template. This keeps the iteration clean and the template reusable.

## A note on execution

Dracon generates configs. It doesn't run them. You can inspect the generated sweep with:

```bash
dracon show sweep.yaml -r
```

For running the generated jobs in parallel, you can pipe the output to whatever executor you prefer, or use [Broodmon](https://github.com/weiss-gal/broodmon) if you want a Dracon-native solution.
