# How-To: Handle Secrets

Managing sensitive information like API keys, passwords, and tokens requires careful handling. Dracon offers several ways to load secrets securely without hardcoding them in your main configuration files.

## Method 1: Environment Variables (Recommended for Deployment)

This is often the most secure and standard way, especially in containerized or cloud environments.

**1. In Your YAML:** Use `${getenv()}` for lazy interpolation or `!include env:` for composition-time loading.

```yaml
database:
  # Lazy interpolation (value retrieved when accessed)
  password_lazy: ${getenv('DB_PASSWORD')}
  # Composition-time include (value loaded when YAML is parsed)
  api_key_compose: !include env:API_KEY

# You can provide defaults to getenv
aws_region: ${getenv('AWS_REGION', 'us-east-1')}
```

**2. Set Environment Variables:** Provide the actual secrets via the environment where your application runs.

```bash
export DB_PASSWORD="my_super_secret_db_password"
export API_KEY="pk_live_xxxxxxxxxxxxxxxxxxxxx"
python your_app.py # Load config as usual
```

**Pros:** Standard practice, decouples secrets from code/config files, easily managed by deployment systems (Docker secrets, Kubernetes secrets, CI/CD variables).
**Cons:** Requires managing environment variables externally.

## Method 2: Separate Secret Files (Good for Local Dev / Simple Cases)

Store secrets in separate files with restricted permissions and include them.

**1. Create Secret Files:**

```text title="config/secrets/db_pass.txt"
my_local_db_password
```

```text title="config/secrets/api_key.secret"
sk_test_yyyyyyyyyyyyyyyyyyyyy
```

**2. Restrict Permissions:**

```bash
chmod 600 config/secrets/*
# Add config/secrets/ to your .gitignore!
```

**3. In Your YAML:** Use `!include file:` with relative paths (using `$DIR` is robust).

```yaml
database:
  username: main_user
  # $DIR refers to the directory of *this* YAML file
  password: !include file:$DIR/secrets/db_pass.txt

api:
  key: !include file:$DIR/secrets/api_key.secret
```

**Pros:** Keeps secrets out of main config and version control (if gitignored), simple for local development.
**Cons:** Requires managing file paths and permissions, potentially less secure than environment variables if files are accidentally committed or exposed.

## Method 3: Custom Loaders (Advanced)

For more complex scenarios (e.g., fetching secrets from Vault, AWS Secrets Manager, Azure Key Vault), create a custom loader function.

**1. Write Loader Function:**

```python
# vault_loader.py
import hvac # Example using HVAC client for HashiCorp Vault

def load_from_vault(path: str, loader=None):
    # path might be "secret/data/myapp#api_key"
    secret_path, key = path.split('#')
    client = hvac.Client(url='http://localhost:8200') # Configure appropriately
    # Assumes AppRole or other auth method is configured
    # client.auth...

    try:
        response = client.secrets.kv.v2.read_secret_version(path=secret_path)
        secret_value = response['data']['data'][key]
        # Custom loaders return (content_string, context_dict)
        return str(secret_value), {'$VAULT_PATH': path}
    except Exception as e:
        raise FileNotFoundError(f"Failed to read secret '{key}' from Vault path '{secret_path}': {e}") from e
```

**2. Register Loader:**

```python
# main.py
import dracon as dr
from vault_loader import load_from_vault

loader = dr.DraconLoader(
    custom_loaders={'vault': load_from_vault}
)
```

**3. Use in YAML:**

```yaml
credentials:
  api_key: !include vault:secret/data/myapp#api_key
  db_pass: !include vault:database/creds/prod#password
```

**Pros:** Highly flexible, integrates with dedicated secret management systems.
**Cons:** Requires writing and maintaining custom loader code, adds external dependencies (like Vault client).

## Choosing the Right Method

- **Deployment (Production, Staging):** Prefer **Environment Variables**.
- **Local Development:** **Environment Variables** (using `.env` files loaded by tools like `python-dotenv` or your shell) or **Separate Secret Files** are common.
- **Complex Secret Management:** Use **Custom Loaders** to integrate with systems like Vault or cloud providers' secret managers.

Always ensure secrets are **never** committed directly into your version control system (Git). Use `.gitignore` effectively.
