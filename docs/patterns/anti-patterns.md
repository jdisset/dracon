# Anti-Patterns

Things to avoid when using Dracon, with concrete alternatives for each.

---

## 1. Escape-hatch fields

**Problem:** you add a loosely-typed field to pass through arbitrary config strings, bypassing the typed composition system entirely.

Bad:

```yaml
# "just throw extra stuff in here"
extra_configs:
  - "--learning-rate=0.01"
  - "--batch-size=64"
```

```python
class TrainConfig(BaseModel):
    model: str
    extra_configs: list[str] = []  # escape hatch
```

This defeats the purpose of typed configs. Typos in `extra_configs` aren't caught. You lose autocomplete, validation, and documentation.

Good:

```yaml
model: resnet
learning_rate: 0.01
batch_size: 64
```

```python
class TrainConfig(BaseModel):
    model: str
    learning_rate: float = 0.001
    batch_size: int = 32
```

If you need to compose config fragments from multiple files, use `<<: !include` to merge them into the typed structure.

---

## 2. Raw strings for structured commands

**Problem:** you construct shell commands or structured data as plain strings when a typed representation exists.

Bad:

```yaml
train_command: "python train.py --model resnet --lr 0.01 --epochs 100"
```

If you need to change the model, you're doing string manipulation. Quoting, escaping, and argument ordering are all manual.

Good:

```yaml
training:
  model: resnet
  learning_rate: 0.01
  epochs: 100
```

Let your Python code turn the structured config into whatever invocation it needs. The config's job is to hold the data, not to format it.

---

## 3. Duplicating definitions

**Problem:** the same block appears in multiple files, maintained separately.

Bad:

```yaml
# dev.yaml
database:
  pool_size: 10
  timeout: 30
  retry: 3

# staging.yaml
database:
  pool_size: 10
  timeout: 30
  retry: 3

# prod.yaml
database:
  pool_size: 10
  timeout: 30
  retry: 3
```

When you need to change `retry` to 5, you update three files. Or you update two and forget the third.

Good:

```yaml
# fragments/database.yaml
pool_size: 10
timeout: 30
retry: 3
```

```yaml
# dev.yaml
database: !include file:$DIR/fragments/database.yaml

# staging.yaml
database: !include file:$DIR/fragments/database.yaml

# prod.yaml
database:
  <<: !include file:$DIR/fragments/database.yaml
  pool_size: 50  # override for prod
```

One definition, included everywhere. Overrides go in the specific file.

---

## 4. Hardcoded absolute paths

**Problem:** configs reference files by absolute path, breaking when the project moves or runs on a different machine.

Bad:

```yaml
dataset: !include file:/home/alice/project/data/config.yaml
weights: /home/alice/models/resnet50.pt
```

Good:

```yaml
# relative to the config file's directory
dataset: !include file:$DIR/data/config.yaml

# from a Python package
defaults: !include pkg:mypackage:defaults.yaml

# from an environment variable
weights: ${getenv('MODEL_DIR')}/resnet50.pt

# or using !include env: for a single value
api_key: !include env:API_KEY
```

`$DIR` resolves to the directory of the file containing the reference. `pkg:` uses Python's package resource system. Both work regardless of where you run dracon from.

---

## 5. Expression interpolation for template invocation

**Problem:** you call an `!fn` template using `${...}` expression syntax when tag syntax is available and clearer.

Bad:

```yaml
!define Agent: !fn
  !require name: "agent name"
  !set_default model: gpt-4
  name: ${name}
  model: ${model}

agents:
  planner: ${Agent(name='planner', model='gpt-4')}
  coder: ${Agent(name='coder')}
```

This works, but the expression syntax is verbose and harder to read. It also loses YAML structure, making the call look like a Python function call embedded in YAML.

Good:

```yaml
!define Agent: !fn
  !require name: "agent name"
  !set_default model: gpt-4
  name: ${name}
  model: ${model}

agents:
  planner: !Agent { name: planner, model: gpt-4 }
  coder: !Agent { name: coder }
```

Tag syntax (`!Agent { ... }`) is more readable, keeps the YAML feel, and makes the intent obvious. Reserve `${...}` for computed values, list comprehensions, and cases where you genuinely need the expression engine (e.g., `${[Agent(name=n) for n in names]}`).

---

## 6. Unnecessary !set_default indirection

**Problem:** you create a variable alias for a config value when users could just override the value directly.

Bad:

```yaml
!set_default _internal_port: 8080

server:
  port: ${_internal_port}
  host: localhost
```

The user has to know that `_internal_port` exists and use `++_internal_port=9090` to change the port. The variable adds a level of indirection without adding value.

Good:

```yaml
server:
  port: 8080
  host: localhost
```

The user overrides directly: `++server.port=9090`. Dracon's CLI path syntax handles nested keys natively. No indirection needed.

Use `!set_default` when the variable is referenced in multiple places (so changing it once changes all of them), or when it appears in dynamic expressions like `!include` paths or `!if` conditions. Don't use it just to give a config leaf a shorter name.
