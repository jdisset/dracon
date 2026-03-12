# Concepts: Interpolation Engine

Dracon's interpolation feature (`${...}`) allows embedding dynamic Python expressions within YAML strings. Understanding how this works, especially regarding lazy evaluation and security, is important.

## How Interpolation Works

Expressions written as `${...}` (or `$(...)` — both syntaxes are identical in behavior) are evaluated **lazily** at construction time, when the value is accessed in Python after the configuration is loaded and composed.

**Mechanism:** During YAML composition, Dracon detects interpolation patterns and creates internal `LazyInterpolable` placeholder objects. When you access `config.my_key`, if `my_key` holds a `LazyInterpolable`, its expression is evaluated at that moment using the captured context and references. If using Dracon's default containers (`Mapping`, `Sequence`), this happens automatically. If using standard `dict`/`list`, resolution might require manual triggering (e.g., `resolve_all_lazy(config)`).

**References:** Expressions can use `@` to reference _final_ constructed values of other keys and `&` to reference _nodes_ during composition (primarily for templating).

!!! note
    Both `${...}` and `$(...)` behave identically — they are both lazy. There is no "immediate" interpolation mode.

## The Evaluation Engine: `asteval` vs. `eval`

Dracon offers two engines for evaluating expressions:

1.  **`asteval` (Default & Recommended):**

    - **Mechanism:** Uses the [asteval library](https://lmfit.github.io/asteval/). `asteval` parses the expression into an Abstract Syntax Tree (AST) and evaluates it in a _sandboxed_ environment.
    - **Safety:** Significantly safer than `eval()`. It prevents the execution of arbitrary code that could perform dangerous operations like filesystem access (`import os; os.remove(...)`), network calls, or accessing sensitive system information. It provides a controlled environment with access only to specified symbols (context variables, safe built-ins).
    - **Limitations:** Might not support every single Python syntax feature or complex metaclasses, but covers the vast majority of use cases needed for configuration. Also I (Jean) couldn't get it to output a clean traceback that shows where in your code an error occured if an expression fails. (If you know how to do this, please let us know)

2.  **`eval` (Use with Extreme Caution):**
    - **Mechanism:** Uses Python's built-in `eval()` function.
    - **Safety:** Well, `eval()` can execute _any_ arbitrary Python code provided in the expression string. If your YAML files come from untrusted sources or could be manipulated, using `eval()` opens a significant security vulnerability. Malicious code could be injected and executed with the permissions of your application.
    - **Use Case:** Only suitable if you have _absolute_ trust in the source and integrity of your configuration files and require features not supported by `asteval`. Can give nice tracebacks if an expression fails.

    !!! warning
        **Security Risk:** Choosing `eval` as the interpolation engine can lead to severe security vulnerabilities if the configuration files are not fully trusted. Avoid using `eval()` unless you are certain of the source and content of the configuration files. Use `eval` at your own risk.

**Choosing the Engine:**

```python
from dracon import DraconLoader

# Default, safe engine
loader_safe = DraconLoader() # interpolation_engine='asteval'

# Use Python's raw eval (DANGEROUS if config is untrusted, or if you're not careful)
loader_raw = DraconLoader(interpolation_engine='eval')

# Disable interpolation entirely
loader_no_interp = DraconLoader(enable_interpolation=False)
```

There's also a `DRACON_EVAL_ENGINE` environment variable that can be set to `asteval` or `eval` to control the default engine.

**Recommendation:** Stick with the default `asteval` engine unless you have a very specific, well-understood need for `eval` and fully control the configuration sources.

## Context and Symbol Availability

Expressions have access to:

- Variables provided via `DraconLoader(context=...)`.
- Variables defined via `!define` / `!set_default`.
- Dracon's default context functions: `getenv`, `getcwd`, `listdir`, `join`, `basename`, `dirname`, `expanduser`, `now`, `construct`.
- File-specific context variables: `DIR`, `FILE`, `FILE_PATH`, `FILE_STEM`, `FILE_EXT`, `FILE_LOAD_TIME`, `FILE_SIZE`.
- `numpy` as `np` (when installed).
- Python built-ins allowed by the engine (`asteval` has a curated list; `eval` has all).
- Special symbols for references (`@`, `&` handled internally before evaluation).
- Helper functions or classes added to the context.
