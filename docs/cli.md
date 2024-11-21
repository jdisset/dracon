# Command Line Programs

Dracon provides utilities to generate command line programs from Pydantic models, leveraging the configuration system for flexible program configuration.

## Basic Usage

Define your program model:

```python
from typing import Annotated
from pydantic import BaseModel
from dracon import Arg, make_program

class DatabaseConfig(BaseModel):
    host: str
    port: int
    username: str
    password: str

class MyProgram(BaseModel):
    database: Annotated[DatabaseConfig, Arg(
        help='Database configuration',
        short='d',
        expand_help=True,
    )]
    verbose: Annotated[bool, Arg(help='Enable verbose output')]

    def run(self):
        # Your program logic here
        if self.verbose:
            print(f"Connecting to {self.database.host}...")
```

Create and run the program:

```python
program = make_program(
    MyProgram,
    name='my-program',
    description='My awesome program'
)

if __name__ == '__main__':
    program_model, args = program.parse_args(sys.argv[1:])
    program_model.run()
```

## Configuration Loading

Your program can load configuration from files:

```yaml
# config.yaml
database:
    host: localhost
    port: 5432
    username: *env:DB_USER
    password: *env:DB_PASSWORD
verbose: false
```

Run with configuration:

```bash
# Load config file
python my_program.py +config.yaml

# Override values
python my_program.py +config.yaml --database.host remotehost --verbose
```

## Argument Annotations

Control how arguments are handled:

```python
class ProcessingConfig(BaseModel):
    input_file: Annotated[str, Arg(
        help='Input file to process',
        short='i',
        is_file=True,
        positional=True
    )]
    output_dir: Annotated[str, Arg(
        help='Output directory',
        short='o',
        is_file=True
    )]
    threads: Annotated[int, Arg(
        help='Number of processing threads',
        short='t',
        default=1
    )]
```

## Resolvable Arguments

Some arguments can be resolved after initialization:

```python
class AdvancedConfig(BaseModel):
    template: Annotated[str, Arg(
        help='Template file',
        is_file=True
    )]
    output: Annotated[str, Arg(
        help='Output file',
        resolvable=True  # Will be resolved after other args
    )]
```

## Custom Actions

Add custom argument actions:

```python
def setup_logging(program: MyProgram, value: Any) -> None:
    level = logging.DEBUG if value else logging.INFO
    logging.basicConfig(level=level)

class LoggingConfig(BaseModel):
    debug: Annotated[bool, Arg(
        help='Enable debug logging',
        action=setup_logging
    )]
```

## Help Messages

Dracon generates formatted help messages:

```bash
$ python my_program.py --help

MyProgram (v1.0.0)
─────────────────

Usage: my-program [OPTIONS]

Options:
  -d, --database DATABASE
    Database configuration
    type: DatabaseConfig
    default: None

  --verbose
    Enable verbose output
    default: False
```

## Advanced Usage

### Environment-Specific Configs

```yaml
# base.yaml
database:
    host: localhost
    port: 5432

# prod.yaml
<<{+<}: *file:base.yaml
database:
    host: prod-db.example.com
    ssl: true
```

Run with environment config:

```bash
python my_program.py +base.yaml +prod.yaml
```

### Dynamic Configuration

```python
class DynamicConfig(BaseModel):
    template: Annotated[str, Arg(
        help='Template file',
        is_file=True
    )]
    variables: Annotated[dict, Arg(
        help='Template variables',
        resolvable=True
    )]

    def resolve_variables(self):
        # Load variables based on template
        with open(self.template) as f:
            template = f.read()
            # Process template to find required variables
            return extract_variables(template)
```

## Best Practices

1. **Structured Configuration**:
   ```python
   class Config(BaseModel):
       input: InputConfig
       processing: ProcessingConfig
       output: OutputConfig
   ```

2. **Clear Help Messages**:
   ```python
   class Config(BaseModel):
       threads: Annotated[int, Arg(
           help='Number of processing threads\n'
                'Use 0 for auto-detection',
           short='t'
       )]
   ```

3. **Default Values**:
   ```python
   class Config(BaseModel):
       log_level: Annotated[str, Arg(
           help='Logging level',
           default='INFO',
       )]
   ```

## Error Handling

```python
try:
    program_model, args = program.parse_args(sys.argv[1:])
except ValidationError as e:
    print("Configuration error:")
    for error in e.errors():
        print(f"  - {error['loc'][0]}: {error['msg']}")
    sys.exit(1)
```
