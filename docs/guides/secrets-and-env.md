# Secrets and Environment

You need to handle passwords, API keys, and environment-specific values without committing them to version control.

## Environment variables in expressions

The `getenv` function is available in all `${...}` expressions:

```yaml
database:
  host: "${getenv('DB_HOST', 'localhost')}"
  password: "${getenv('DB_PASSWORD')}"
```

This is lazy: the expression evaluates when the value is accessed, not when the file is parsed. If `DB_PASSWORD` is not set, you'll get `None` (Python's `os.getenv` behavior).

You can also use the shorthand `$` syntax for simple variable references:

```yaml
api_url: "${getenv('API_URL', 'https://api.example.com')}"
```

## !include env:VAR_NAME

For values that should be loaded at composition time (not lazily), use the `env:` loader:

```yaml
api_key: !include env:API_KEY
```

This reads the environment variable `API_KEY` during composition and inlines its value. If the variable is not set, composition fails with an error.

The difference from `${getenv(...)}`: the `env:` loader runs during composition and fails loudly if the variable is missing. `getenv()` runs lazily and returns `None` by default.

## Separate secret files

Keep secrets in files that are gitignored:

```yaml
database:
  host: db.example.com
  port: 5432
  password: !include file:$DIR/secrets/db-pass.txt
```

`$DIR` is automatically set to the directory containing the current YAML file, so relative paths work regardless of where you run from.

The `secrets/db-pass.txt` file contains just the raw password, nothing else:

```
s3cr3t-p4ssw0rd
```

## Optional overlays for local dev

Use `!include?` (with the question mark) to include a file only if it exists:

```yaml
database:
  host: db.example.com
  port: 5432

<<{<+}: !include? file:$DIR/local.yaml
```

If `local.yaml` exists, its values merge in and override the defaults. If it doesn't exist, the include is silently skipped. This lets each developer have a `local.yaml` that's gitignored, without breaking anything for people who don't have one.

## Pattern: !require for mandatory variables

Use `!require` to declare that a variable must be set before the config can be used:

```yaml
!require api_key: "Set the API_KEY env variable or pass ++api_key=..."

endpoints:
  auth: "https://api.example.com/auth?key=${api_key}"
```

If `api_key` is not in the context when the config is composed, Dracon raises a `CompositionError` with the hint message. The caller can provide it via:

- CLI context variable: `++api_key=sk-abc123` (injects into `${...}` expressions)
- Shell environment via CLI: `++api_key="$API_KEY"` (the shell expands `$API_KEY` before dracon sees it)
- Python: `dracon.load('config.yaml', context={'api_key': 'sk-abc123'})`
- Or use `!include env:API_KEY` / `${getenv('API_KEY')}` in the YAML itself instead of `!require`

## .gitignore patterns

Add these to your `.gitignore`:

```gitignore
# dracon secrets
*.secret
*.secret.yaml
secrets/
local.yaml
local.*.yaml
.env
```

## Putting it together

A typical setup:

```yaml title="config.yaml"
!require api_key: "Set API_KEY or pass ++api_key=..."

database:
  host: "${getenv('DB_HOST', 'localhost')}"
  port: 5432
  password: !include file:$DIR/secrets/db-pass.txt

api:
  key: "${api_key}"
  base_url: "https://api.example.com"

# local overrides (gitignored)
<<{<+}: !include? file:$DIR/local.yaml
```

```yaml title="local.yaml (gitignored)"
database:
  host: localhost
  port: 5433
api:
  base_url: "http://localhost:8080"
```

Secrets stay out of version control. Local dev overrides are optional. Required values fail loudly with helpful messages.
