# Pattern: The Dynamic Skeleton

## The problem

You're training ML models. You have 5 datasets and 4 hyperparameter presets. Without any composition strategy, that's 20 config files, and most of them are near-identical. Add a 6th dataset and you're writing 4 more files. Add a new preset and you're writing 5 more.

The skeleton pattern brings this down to 1 + M + N files. One skeleton, M dataset definitions, N hyperparameter presets. Adding a dataset means adding one file. Adding a preset means adding one file.

## The components

The pattern has four parts:

1. **The Skeleton** (`start.yaml`): the entry point that wires everything together
2. **The Payloads** (`datasets/*.yaml`): composable dataset definitions
3. **The Logic** (`configs/*.yaml`): hyperparameter presets
4. **The Python Bridge**: runtime code that injects live objects into deferred nodes

### File layout

```
training/
  start.yaml              # the skeleton
  datasets/
    genomics.yaml
    proteomics.yaml
    synthetic.yaml
  configs/
    regression.yaml
    classification.yaml
    transformer.yaml
```

## The skeleton

`start.yaml` declares variables with `!set_default`, uses them in `!include` paths, and defers the parts that need runtime objects.

```yaml
# start.yaml

# -- interface: these are the "knobs" the caller sets --
!set_default training_set_file: "datasets/genomics.yaml"
!set_default base_config: "regression"

# -- dataset: pulled in from a file chosen at invocation --
!define dataset_name: "${training_set_file.split('/')[-1].split('.')[0]}"
dataset: !include file:$DIR/${training_set_file}

# -- hyperparameters: layered on top with merge --
<<{+>}: !include file:$DIR/configs/${base_config}.yaml

# -- training core --
epochs: 100
batch_size: 32
output_dir: "/results/${dataset_name}/${base_config}"

# -- loggers: deferred because they need live runtime objects --
loggers: !deferred
  wandb:
    project: "biocomp-${dataset_name}"
    run_name: "${run_id}"
    experiment: ${experiment_tracker}
  csv:
    path: "/results/${dataset_name}/${base_config}/${run_id}/metrics.csv"
```

A few things to note:

- `!set_default` declares variables with fallback values. The caller can override them from the CLI or from a parent config. If nobody overrides them, the defaults apply.
- `!include file:$DIR/${training_set_file}` is a dynamic include. The path depends on a variable. `$DIR` resolves to the directory containing `start.yaml`.
- `<<{+>}:` is a merge operator. It pulls in the hyperparameter preset and merges it into the current level. The `+>` strategy means "add new keys, override existing ones from right."
- The `loggers` block is `!deferred` because `run_id` and `experiment_tracker` are runtime-only values.

### A dataset payload

```yaml
# datasets/genomics.yaml
name: "human-genome-v3"
path: "/data/genomics/hg38"
num_features: 22400
normalization: "log1p"
splits:
  train: 0.8
  val: 0.1
  test: 0.1
```

Nothing special. Just data. The skeleton pulls it in and slots it under `dataset`.

### A hyperparameter preset

```yaml
# configs/regression.yaml
learning_rate: 0.001
optimizer: "adam"
loss: "mse"
scheduler:
  type: "cosine"
  warmup_steps: 500
```

Also just data. The merge operator in the skeleton folds these keys into the top-level config.

## CLI execution

With Dracon's CLI support, you can override the skeleton's defaults from the command line:

```bash
# use default dataset (genomics) and default config (regression)
biocomp-train +start.yaml

# use a different dataset
biocomp-train +start.yaml ++training_set_file=datasets/proteomics.yaml

# use a different config
biocomp-train +start.yaml ++base_config=transformer

# combine both
biocomp-train +start.yaml \
  ++training_set_file=datasets/synthetic.yaml \
  ++base_config=classification
```

The `+start.yaml` loads the skeleton as a config file. The `++key=value` syntax overrides `!set_default` variables before composition. So `++training_set_file=datasets/proteomics.yaml` changes which dataset file gets `!include`d, and the rest flows from there.

## The Python bridge

The runtime code loads the config, generates a run ID, and constructs the deferred loggers:

```python
# train.py
import uuid
import dracon

config = dracon.load("start.yaml")

run_id = str(uuid.uuid4())[:8]
experiment_tracker = init_wandb(project=config["loggers"])  # your init code

# construct the deferred loggers with runtime objects
loggers = config["loggers"].construct(context={
    "run_id": run_id,
    "experiment_tracker": experiment_tracker,
})

print(f"Training {config['dataset']['name']}")
print(f"Output:  {config['output_dir']}")
print(f"Loggers: wandb={loggers['wandb']['project']}, csv={loggers['csv']['path']}")
```

## What happens internally

Four steps, in order:

1. **Load**: Dracon reads `start.yaml` and encounters the `!set_default` variables. If the caller provided overrides (via CLI `++` or a parent config), those take precedence.

2. **Dynamic includes**: `!include file:$DIR/${training_set_file}` resolves the variable, finds the file, and pulls it in. Same for the hyperparameter preset. The `$DIR` token resolves to the directory of the file containing the `!include`.

3. **Composition**: Merge operators (`<<{+>}:`) fold the included content into the tree. Interpolations like `${dataset_name}` are evaluated. The `!deferred` subtree is skipped entirely and stored as a frozen `DeferredNode`.

4. **Construction**: The non-deferred parts become a dict-like config object. When you call `.construct(context=...)` on the deferred loggers, Dracon resumes composition and construction for that subtree, using the runtime context you provided.

## Why this works

**Combinatorial reduction.** 5 datasets and 4 presets = 9 files + 1 skeleton, not 20. The 6th dataset is one file, not 4.

**Context awareness.** `$DIR` in include paths means files can reference neighbors without hardcoded absolute paths. Move the whole directory and nothing breaks.

**Runtime injection.** The `!deferred` loggers don't try to create a wandb connection at config load time. That would fail in CI, in tests, or anywhere wandb isn't configured. The connection is created only when the training code explicitly asks for it, with the right credentials.

**Override ergonomics.** A single `++training_set_file=datasets/new_data.yaml` on the command line rewires the entire pipeline. No editing config files, no copy-paste, no forgetting to update one of 20 copies.
