# Tutorial 4: Dynamic Configs

So far, your webmon configs have been static: you list your sites, set your intervals, and you're done. But what happens when you need to monitor 20 sites, each with slightly different check intervals, custom headers, or per-site notification rules?

You could copy-paste 20 blocks. Or you could let the config generate itself.

Dracon has a set of composition instructions (`!define`, `!if`, `!each`, `!fn`) that run at load time and produce the final config. Think of them as a lightweight templating layer that lives inside YAML.

**Time: ~15 minutes.**

## Variables with !define

The simplest instruction. `!define` creates a variable that you can use in `${...}` interpolations anywhere below it:

```yaml
# config/base.yaml
!define environment: dev

database:
  host: "db.${environment}.internal"
  port: 5432
  name: "webmon_${environment}"
```

After composition, the `!define` line disappears and the interpolations resolve:

```yaml
database:
  host: db.dev.internal
  port: 5432
  name: webmon_dev
```

The variable `environment` is available to everything in the same scope (the mapping where it was defined, and anything nested inside it).

## Soft defaults with !set_default

`!define` always sets the variable, overwriting any previous value. Sometimes you want a fallback that only applies when the caller hasn't provided one. That's `!set_default`:

```yaml
# config/base.yaml
!set_default environment: dev
!set_default log_level: INFO

database:
  host: "db.${environment}.internal"
log_level: ${log_level}
```

If someone loads this file and passes `++environment=prod` from the CLI (or defines `environment` in an outer file), the `!set_default` is skipped. If they don't, it falls back to `dev`.

The rule is simple:

- `!define` always wins. It sets the variable unconditionally.
- `!set_default` only sets it if nobody else has.

Use `!set_default` in base/template files. Use `!define` in the files that make the final call.

## Contracts with !require

When you write a config fragment meant to be included by other files, you sometimes need the caller to provide certain variables. `!require` declares that contract:

```yaml
# config/notifications/email-template.yaml
!require notify_email: "Email address for alerts (e.g. ops@example.com)"
!require environment: "Deployment environment"

email:
  to: ${notify_email}
  subject: "[webmon] [${environment}] Site down"
  from: "webmon-${environment}@example.com"
```

If this file is included without `notify_email` or `environment` being defined somewhere, composition fails with a clear error:

```
required variable 'notify_email' not provided
  hint: Email address for alerts (e.g. ops@example.com)
```

The hint message is just for humans reading the error. Make it useful.

## Conditionals with !if

You want SSL settings in prod but not in dev. `!if` handles that.

### Shorthand form

The short form includes a block only when the condition is truthy:

```yaml
!define environment: prod

database:
  host: "db.${environment}.internal"
  port: 5432

!if ${environment == 'prod'}:
  ssl:
    cert: /etc/ssl/webmon.pem
    key: /etc/ssl/webmon.key
  log_level: WARN
```

When `environment` is `prod`, the `ssl` and `log_level` keys are added to the mapping. When it's anything else, they're left out entirely.

### Then/else form

For choosing between two options:

```yaml
!define environment: prod

database:
  !if ${environment == 'prod'}:
    then:
      host: db.prod.internal
      password: ${getenv('PROD_DB_PASSWORD')}
    else:
      host: localhost
      password: dev-pass
  port: 5432
```

The `then` branch is used when the condition is truthy, `else` when it's falsy. The `then`/`else` wrapper keys are removed; their contents get spliced into the parent.

## Iteration with !each

This is the one that saves you from copy-pasting. `!each` repeats a block for every item in a list.

### Generating a list

Say you want to create a monitoring config entry for each site:

```yaml
!define sites:
  - example.com
  - status.example.com
  - api.example.com

checks:
  !each(site) ${sites}:
    - url: "https://${site}"
      interval: 30
      timeout: 10
```

After composition:

```yaml
checks:
  - url: https://example.com
    interval: 30
    timeout: 10
  - url: https://status.example.com
    interval: 30
    timeout: 10
  - url: https://api.example.com
    interval: 30
    timeout: 10
```

The `!each(site)` tag declares the loop variable. The key expression `${sites}` is what gets iterated over. The value (the `- url: ...` block) is the template that gets duplicated for each item.

### Generating a map

You can also produce mapping entries with dynamic keys. This requires the keys to be interpolated so they're unique:

```yaml
!define regions:
  - us-east
  - eu-west
  - ap-south

endpoints:
  !each(region) ${regions}:
    ${region}: "https://${region}.monitor.example.com"
```

Result:

```yaml
endpoints:
  us-east: https://us-east.monitor.example.com
  eu-west: https://eu-west.monitor.example.com
  ap-south: https://ap-south.monitor.example.com
```

You can also iterate over more structured data. If your items are dicts, just access their fields:

```yaml
!define sites:
  - { name: example.com, interval: 30 }
  - { name: api.example.com, interval: 10 }
  - { name: status.example.com, interval: 60 }

checks:
  !each(site) ${sites}:
    - url: "https://${site['name']}"
      interval: ${site['interval']}
      timeout: 10
```

## Inline functions with !fn

When your template block is more than a few lines, or you want to reuse it in multiple places, extract it into a function with `!fn`:

```yaml
!define make_check: !fn
  !require site_name: "domain to monitor"
  !set_default interval: 30
  !set_default timeout: 10
  url: "https://${site_name}"
  interval: ${interval}
  timeout: ${timeout}
  health_endpoint: "https://${site_name}/health"
```

This defines `make_check` as a callable template. The `!require` and `!set_default` lines declare its parameters: `site_name` is required, `interval` and `timeout` have defaults.

### Calling with a tag

You call it by using the function name as a YAML tag:

```yaml
checks:
  primary: !make_check { site_name: example.com }
  api: !make_check { site_name: api.example.com, interval: 10 }
  status: !make_check
    site_name: status.example.com
    interval: 60
    timeout: 30
```

Both the flow syntax (`{ key: value }`) and block syntax work. The result of each call is the template body with the arguments substituted in:

```yaml
checks:
  primary:
    url: https://example.com
    interval: 30
    timeout: 10
    health_endpoint: https://example.com/health
  api:
    url: https://api.example.com
    interval: 10
    timeout: 10
    health_endpoint: https://api.example.com/health
  status:
    url: https://status.example.com
    interval: 60
    timeout: 30
    health_endpoint: https://status.example.com/health
```

### Calling from expressions

You can also call `!fn` templates inside `${...}` interpolations:

```yaml
fast_check: ${make_check(site_name='api.example.com', interval=5)}
```

This is handy when you need the result as part of a larger expression.

## Combining everything

Here's a real-world-ish example that uses `!define`, `!each`, `!if`, and `!fn` together. The goal: generate monitoring configs for multiple sites, with SSL checks only in prod.

```yaml
# config/monitoring.yaml

!set_default environment: dev

!define sites:
  - { name: example.com, interval: 30, critical: true }
  - { name: api.example.com, interval: 10, critical: true }
  - { name: docs.example.com, interval: 120, critical: false }

!define make_check: !fn
  !require site: "site config dict"
  url: "https://${site['name']}"
  interval: ${site['interval']}
  timeout: 10
  !if ${site['critical']}:
    notify: ops@example.com
    priority: high
  !if ${environment == 'prod'}:
    ssl_verify: true
    ssl_expiry_warn_days: 30

checks:
  !each(site) ${sites}:
    ${site['name']}: !make_check { site: "${site}" }
```

Load it and check the result:

```bash
dracon show config/monitoring.yaml ++environment=prod -r
```

Output:

```yaml
checks:
  example.com:
    url: https://example.com
    interval: 30
    timeout: 10
    notify: ops@example.com
    priority: high
    ssl_verify: true
    ssl_expiry_warn_days: 30
  api.example.com:
    url: https://api.example.com
    interval: 10
    timeout: 10
    notify: ops@example.com
    priority: high
    ssl_verify: true
    ssl_expiry_warn_days: 30
  docs.example.com:
    url: https://docs.example.com
    interval: 120
    timeout: 10
    ssl_verify: true
    ssl_expiry_warn_days: 30
```

Notice that `docs.example.com` doesn't have `notify` or `priority` (because `critical` is false), but it still has the SSL settings (because we're in prod). Switch to `++environment=dev` and all the SSL lines vanish.

That's 50 lines of config generating a fully-typed monitoring setup for any number of sites, with environment-aware behavior.

## What you've learned

- `!define` sets a variable unconditionally; `!set_default` sets it only if not already provided
- `!require` declares that a variable must be provided, with a hint message for the error
- `!if` conditionally includes blocks, with a shorthand form (include-or-not) and a `then`/`else` form
- `!each(var) ${list}:` iterates over a list, duplicating its body for each item. Works for both list and map generation.
- `!fn` defines a reusable template with parameters (`!require` for required, `!set_default` for optional). Call it as a tag (`!name { args }`) or from an expression (`${name(args)}`)
- These instructions compose naturally: `!each` can call `!fn`, `!fn` bodies can contain `!if`, and so on
