# Advanced: Resolvable Values

While [Deferred Nodes](deferred.md) pause the construction of an entire configuration branch, `Resolvable[T]` provides a way to defer the final processing or validation of a _single value_ after the initial configuration object has been loaded.

It's less about delaying construction and more about having a placeholder that requires an explicit `.resolve()` call to get its final form, often after other application setup or command-line argument parsing is complete.

## Why Use Resolvable?

- **CLI Argument Post-Processing:** An argument might need validation or transformation based on _other_ arguments or loaded configuration values that aren't available during the initial `parse_args`.
- **Inter-dependent Fields:** A field's final value might depend on another field that itself might be complex or deferred.
- **User-Provided Hooks:** Allow users to configure values that need a final check or modification step within the application logic.

## Syntax and Usage

1.  **Type Hint:** Use `Resolvable[YourType]` in your Pydantic model.

    ```python
    from pydantic import BaseModel
    from dracon import Resolvable

    class AppConfig(BaseModel):
        input_file: str
        # output_file depends on input_file, mark as Resolvable
        output_file: Resolvable[str]
        threshold: float
    ```

2.  **YAML Tag:** You can also use the `!Resolvable` or `!Resolvable[YourType]` tag in YAML, though using the type hint is more common, especially with the CLI.
    ```yaml
    config:
        value: !Resolvable[int] "10" # Value is initially string "10"
    ```

## The `Resolvable` Object

When Dracon loads a field marked as `Resolvable[T]` (either by type hint or tag), it creates a `dracon.resolvable.Resolvable` object instead of immediately trying to create an object of type `T`. This `Resolvable` object stores:

- The underlying YAML **node** representing the value.
- A reference to the **constructor** (`Draconstructor`) used.
- The expected inner **type** (`T`).

```python
# Example using the AppConfig above
loader = DraconLoader(context={'AppConfig': AppConfig})
config = loader.load("config.yaml") # Assume output_file is defined

assert isinstance(config.output_file, Resolvable)
print(config.output_file.node) # Shows the YAML node for output_file
```

## Manual Resolution: `.resolve()`

To get the final value of type `T`, you call the `.resolve()` method on the `Resolvable` instance. This triggers the Dracon constructor to process the stored node, applying any necessary context and attempting to construct an object of the inner type `T`.

```python
# ... continued
from dracon import DraconLoader, Resolvable, Arg, make_program # CLI parts
import sys

class AppConfig(BaseModel):
    input_file: Annotated[str, Arg(positional=True)]
    # Mark output_file as resolvable in the CLI Arg
    output_file: Annotated[Resolvable[str], Arg(resolvable=True)]
    # This field is NOT resolvable
    threshold: float = 0.5

program = make_program(AppConfig)
config, _ = program.parse_args(sys.argv[1:])

# config.output_file is still a Resolvable object here
assert isinstance(config.output_file, Resolvable)

# --- Application Logic ---
# Maybe determine the actual output path based on input
if config.output_file.empty(): # Check if a value was provided
    derived_output_path = config.input_file + ".out"
    # We can't just assign the string, we need to resolve the underlying
    # structure (even if simple) via the constructor
    # A bit verbose for simple strings, but necessary for consistency
    final_output_file = config.output_file.resolve(
        context={'derived_path': derived_output_path} # Hypothetical context
    )
    # Or, more simply for just overriding the value if empty:
    final_output_file = derived_output_path # Direct assignment after check
else:
    # Resolve the value provided by the user/config
    final_output_file = config.output_file.resolve()

print(f"Input: {config.input_file}")
print(f"Output: {final_output_file}") # Now it's a string
print(f"Threshold: {config.threshold}")

assert isinstance(final_output_file, str)
```

## `Resolvable` vs. `DeferredNode`

While both delay processing, they serve different purposes:

| Feature         | `Resolvable[T]`                       | `DeferredNode`                       |
| :-------------- | :------------------------------------ | :----------------------------------- |
| **Granularity** | Single value / field                  | Entire node branch                   |
| **Purpose**     | Delay final validation/processing     | Delay composition & construction     |
| **Trigger**     | Manual call to `.resolve()`           | Manual call to `.construct()`        |
| **Input**       | Typically loaded value/node           | Captures node & context state        |
| **Output**      | Aims for type `T`                     | Constructs object based on node/tag  |
| **Use Case**    | CLI post-processing, inter-field deps | Late context binding, resource mgmt. |

Use `Resolvable` when you have the configuration structure loaded but need a final application-level step to finalize a specific _value_. Use `DeferredNode` when you need to postpone the entire _construction_ of a component until later, often because necessary context is missing during the initial load.
