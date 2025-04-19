# Advanced: Deferred Nodes

Sometimes, you need more control over _when_ a part of your configuration is fully processed and constructed into a Python object. Deferred nodes allow you to pause the composition and construction process for a specific node until you explicitly trigger it later in your code.

## Why Use Deferred Nodes?

- **Late-Binding Context:** You need to provide context (variables, functions) that is only available _after_ the main configuration has been loaded (e.g., secrets loaded from a vault, runtime parameters).
- **Conditional Construction:** You want to decide whether or how to construct a component based on other parts of the loaded configuration.
- **Performance:** Avoid constructing complex or resource-intensive objects until they are actually needed.
- **Manual Orchestration:** Explicitly control the order of object initialization when dependencies exist.

## Syntax

1.  **`!deferred` Tag:** Apply the tag directly to the node you want to defer.

    ```yaml
    database_connection: !deferred # Defer construction of this mapping
      host: db.example.com
      port: 5432
      password: ${DB_PASSWORD} # Needs DB_PASSWORD in context later
    ```

2.  **`!deferred:TypeName` Tag:** Defer construction _and_ specify the target type.

    ```yaml
    # Defer construction, expecting a DatabaseConfig object eventually
    database: !deferred:DatabaseConfig
      host: db.example.com
      port: 5432
      password: ${DB_PASSWORD}
    ```

3.  **`!deferred::clear_ctx=var1,var2` Tag:** Defer construction and specify context variables that should be _ignored_ from the parent scope when this node is eventually constructed. This isolates the deferred node's context.

    ```yaml
    !define ENV: production

    component: !deferred::clear_ctx=ENV # Don't inherit ENV
      !define ENV: development # Use a local ENV for this component
      setting: ${ENV} # Will resolve to 'development'
    ```

4.  **`DraconLoader(deferred_paths=...)`:** Force nodes matching specific [KeyPaths](keypaths.md) to be deferred, even without an explicit tag.
    ```python
    # Force anything under 'services.*.database' to be deferred
    loader = DraconLoader(deferred_paths=['/services/*/database'])
    config = loader.load('config.yaml')
    # config.services.web.database will be a DeferredNode
    ```

## The `DeferredNode` Object

When Dracon encounters a node marked for deferral, it doesn't construct it immediately. Instead, it creates a `dracon.deferred.DeferredNode` object. This object acts as a placeholder and contains:

- The original YAML **node structure**.
- A **snapshot of the context** available at that point in the composition.
- A reference to the **`DraconLoader`** instance used.
- The full **`CompositionResult`** at the time of deferral.

This captured state allows the construction process to be resumed later accurately.

```python
from dracon import DraconLoader
from dracon.deferred import DeferredNode

loader = DraconLoader()
yaml_content = '''
api_client: !deferred
    base_url: "https://api.example.com"
    api_key: ${API_KEY}
'''
config = loader.loads(yaml_content)

# config.api_client is NOT the final dict/object yet
assert isinstance(config.api_client, DeferredNode)
print(config.api_client)
# Output: DeferredNode(...)
```

## Manual Construction: `.construct()`

To get the actual Python object, you call the `.construct()` method on the `DeferredNode` instance.

```python
# ... (previous example continued)

# Provide the missing context variable when constructing
runtime_context = {'API_KEY': 'my-secret-key-123'}
final_api_client = config.api_client.construct(context=runtime_context)

# Now final_api_client is the constructed object (likely a dict or custom class)
print(final_api_client)
# Output might be: {'base_url': 'https://api.example.com', 'api_key': 'my-secret-key-123'}

# You can optionally replace the deferred node in your config object
config.api_client = final_api_client
```

### Selective Deferral within `.construct()`

You can even defer sub-parts _within_ the manually constructed node using the `deferred_paths` argument in `.construct()`. Paths are relative to the deferred node itself.

```python
complex_service: !deferred
  database:
    host: db
    credentials: ${DB_CREDS} # Needs late binding
  cache:
    host: cache
    credentials: ${CACHE_CREDS} # Needs late binding

# --- Python ---
deferred_node = config.complex_service

# Construct the service, but keep 'database' and 'cache' deferred
partially_constructed = deferred_node.construct(
    deferred_paths=['/database', '/cache'] # Paths relative to complex_service
)

assert isinstance(partially_constructed.database, DeferredNode)
assert isinstance(partially_constructed.cache, DeferredNode)

# Later, construct the database part
db_creds = get_database_credentials()
final_db = partially_constructed.database.construct(context={'DB_CREDS': db_creds})

# And the cache part
cache_creds = get_cache_credentials()
final_cache = partially_constructed.cache.construct(context={'CACHE_CREDS': cache_creds})
```

## Context Handling

- A `DeferredNode` captures the context present when it was created during the initial load.
- Context provided via `.construct(context=...)` is **merged** with the captured context. By default, the provided runtime context takes priority (`{<~}`).
- Variables specified in `!deferred::clear_ctx=...` are removed from the captured context before merging, preventing inheritance from the parent scope.

## Pickling and Parallelism

`DeferredNode` objects (along with the `DraconLoader` and `CompositionResult` they reference) are designed to be picklable (using Python's `pickle` or `dill`).

This allows you to:

1.  Load a configuration containing deferred nodes.
2.  Send these `DeferredNode` objects to different processes or machines (e.g., using `multiprocessing`).
3.  Provide process-specific context and call `.construct()` in parallel to build different components independently.

```python
import multiprocessing
import pickle
from dracon import DraconLoader
from dracon.deferred import DeferredNode

# --- config.yaml ---
# workers:
#   - !deferred::clear_ctx=WORKER_ID
#     id: ${WORKER_ID}
#     config:
#       param: ${WORKER_ID * 10}
#   - !deferred::clear_ctx=WORKER_ID
#     id: ${WORKER_ID}
#     config:
#       param: ${WORKER_ID * 10}

def process_worker(pickled_deferred_node_data):
    worker_id, pickled_node = pickled_deferred_node_data
    # Unpickle the node in the new process
    deferred_node = pickle.loads(pickled_node)
    # Construct with process-specific context
    worker_config = deferred_node.construct(context={'WORKER_ID': worker_id})
    print(f"Worker {worker_id} constructed: {worker_config}")
    return worker_config

if __name__ == "__main__":
    loader = DraconLoader()
    config = loader.load('config.yaml')

    deferred_workers = config.workers
    pickled_workers = []
    for i, node in enumerate(deferred_workers):
        assert isinstance(node, DeferredNode)
        pickled_workers.append((i, pickle.dumps(node))) # Pass ID and pickled node

    with multiprocessing.Pool(processes=len(pickled_workers)) as pool:
        results = pool.map(process_worker, pickled_workers)

    print("All workers processed.")
```
