# Tutorial 3: Compose Configs

In Tutorial 2, you ran webmon from the command line with a single config file. But real projects don't stay that simple for long. You end up with a dev environment, a staging environment, a production environment, and they share 80% of the same config with a few differences: database host, check interval, who gets notified.

Copy-pasting configs and keeping them in sync is the road to subtle bugs. This tutorial shows how to layer configs instead.

**Time: ~15 minutes.**

## The problem

Here's what you need for webmon across two environments:

| Setting | Dev | Prod |
|---|---|---|
| database.host | localhost | db.prod.internal |
| database.port | 5432 | 5432 |
| check_interval | 60 | 15 |
| notify_email | (empty) | ops@example.com |
| log_level | DEBUG | WARN |

Most of this is the same. The database port, the site list, the database name -- all shared. Only a handful of values change per environment.

## File layout

Set up a config directory like this:

```
config/
  base.yaml
  env/
    dev.yaml
    prod.yaml
  notifications/
    slack.yaml
  local-overrides.yaml   # (optional, gitignored)
```

## The base config

Start with the shared defaults:

```yaml
# config/base.yaml
sites:
  - https://example.com
  - https://status.example.com

check_interval: 60
log_level: INFO
notify_email: ""

database:
  host: localhost
  port: 5432
  name: webmon
  password: ${getenv('WEBMON_DB_PASSWORD', 'dev-pass')}
```

Nothing fancy. This is the config that works for local development as-is.

## Environment overrides

Now write the prod overlay. It only contains the values that differ:

```yaml
# config/env/prod.yaml
check_interval: 15
log_level: WARN
notify_email: ops@example.com

database:
  host: db.prod.internal
  password: ${getenv('WEBMON_DB_PASSWORD')}

<<{<+}: !include file:$DIR/../base.yaml
```

The last line does the work. Let's unpack it:

- `<<:` is the merge key. It says "merge another mapping into this one."
- `!include file:$DIR/../base.yaml` loads the base config. `$DIR` is always the directory of the current file, so this resolves to `config/base.yaml` regardless of where you invoke things from.
- `{<+}` is the merge strategy. The `<` means "the existing values (prod.yaml) win conflicts." The `+` means "merge dictionaries recursively instead of replacing them." So prod.yaml's `database.host` overrides the base, but `database.port` and `database.name` are kept from the base.

Without the `+`, the entire `database` mapping in prod would replace the base one, and you'd lose `port` and `name`. With `+`, they merge field by field.

!!! tip
    Think of `{<+}` as "I win, merge deep." You'll use this one a lot.

## Loading multiple files

There are two ways to compose configs. The merge-key approach above (putting `<<:` inside the file itself) is one. The other is to pass multiple files when loading:

```python
import dracon

config = dracon.load(["config/base.yaml", "config/env/prod.yaml"])
```

When you pass a list, files are merged left to right. Later files override earlier ones. This is equivalent to what the `<<{<+}:` line does, but controlled from the loading side instead of inside the YAML.

From the CLI, it's the same idea:

```bash
python webmon.py +config/base.yaml +config/env/prod.yaml
```

Both approaches work. The in-file merge key is better when a file always needs its base. The multi-file approach is better when the caller decides what to layer.

## Including fragments

Say your notification settings are complex enough to warrant their own file:

```yaml
# config/notifications/slack.yaml
slack:
  webhook: ${getenv('SLACK_WEBHOOK_URL', '')}
  channel: "#ops-alerts"
  mention_on_failure: "@oncall"
```

Pull it into your prod config:

```yaml
# config/env/prod.yaml
check_interval: 15
log_level: WARN
notify_email: ops@example.com

notifications: !include file:$DIR/../notifications/slack.yaml

database:
  host: db.prod.internal
  password: ${getenv('WEBMON_DB_PASSWORD')}

<<{<+}: !include file:$DIR/../base.yaml
```

`!include file:...` replaces itself with the contents of the included file. The `$DIR` variable always refers to the directory of the file that contains the `!include`, so relative paths work correctly even when files include each other across directories.

## Optional includes

Not every developer on your team needs the same local tweaks. You can use `!include?` (note the `?`) to include a file only if it exists:

```yaml
# config/env/dev.yaml
<<{<+}: !include file:$DIR/../base.yaml
<<{<+}: !include? file:$DIR/../local-overrides.yaml
```

If `local-overrides.yaml` is there, it gets merged in. If it's missing, nothing happens, no error. This is good for things like personal debug settings or machine-specific paths that you `.gitignore`.

A typical `local-overrides.yaml` might look like:

```yaml
# config/local-overrides.yaml  (gitignored)
database:
  host: 192.168.1.100
  password: my-local-pass

log_level: DEBUG
```

## The layering pattern

The general pattern for environment configs looks like this:

```
base.yaml          -- shared defaults
  env/dev.yaml     -- dev overrides (merges base)
  env/prod.yaml    -- prod overrides (merges base)
  env/staging.yaml -- staging overrides (merges base)
```

Each environment file includes the base with `<<{<+}:` and overrides only what it needs. When you add a new shared setting to `base.yaml`, every environment gets it automatically.

## Precedence

When using `@dracon_program` and the CLI (Tutorial 2), values come from multiple sources. Here's the order, from lowest to highest priority:

| Priority | Source | Example |
|---|---|---|
| 1 (lowest) | Model field defaults | `check_interval: int = 60` |
| 2 | Auto-discovered configs | `config_files=[ConfigFile("~/.webmon.yaml")]` |
| 3 | `+file` positional args | `+config/prod.yaml` |
| 4 (highest) | `--flag` CLI overrides | `--check-interval 10` |

Higher priority sources override lower ones. So if your model defaults `check_interval` to 60, your config file sets it to 15, and you pass `--check-interval 10` on the command line, you get 10.

When using `dracon.load()` directly (no CLI), it's simpler: you just get the result of merging the files you passed in, left to right.

## Verifying composition

Before you wire things up, check what the final composed config looks like:

```bash
dracon show config/base.yaml config/env/prod.yaml
```

This loads both files, merges them, and prints the result as YAML. You'll see the merged output with all includes resolved.

Add `-r` to also resolve interpolations (like `${getenv(...)}`):

```bash
dracon show config/base.yaml config/env/prod.yaml -r
```

Output (roughly):

```yaml
sites:
  - https://example.com
  - https://status.example.com
check_interval: 15
log_level: WARN
notify_email: ops@example.com
notifications:
  slack:
    webhook: ''
    channel: '#ops-alerts'
    mention_on_failure: '@oncall'
database:
  host: db.prod.internal
  port: 5432
  name: webmon
  password: ''
```

This is your "what does prod actually look like?" sanity check.

## Putting it together

Here's the full dev workflow:

1. Edit `base.yaml` for shared settings.
2. Edit `env/prod.yaml` (or `dev.yaml`, `staging.yaml`) for environment-specific overrides.
3. Run `dracon show config/base.yaml config/env/prod.yaml -r` to check.
4. Run your app: `python webmon.py +config/env/prod.yaml`

Or, if your environment files already include the base via `<<{<+}:`, you only need one file:

```bash
python webmon.py +config/env/prod.yaml
```

## What you've learned

- Use `<<{<+}: !include file:$DIR/base.yaml` to merge a base config into an override file, with recursive dict merging and existing values winning
- Pass multiple files to `dracon.load(["base.yaml", "prod.yaml"])` or `+base.yaml +prod.yaml` for caller-controlled layering
- `!include file:$DIR/...` pulls in fragments; `$DIR` is always the current file's directory
- `!include?` silently skips missing files, good for optional local overrides
- Precedence: model defaults < auto-discovered configs < +files < --flags
- `dracon show file1.yaml file2.yaml -r` lets you inspect the composed result

Next up: [Tutorial 4: Dynamic Configs](04-dynamic-configs.md), where you use variables, conditionals, and loops to generate config programmatically.
