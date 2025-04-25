from pydantic import BaseModel, Field
from typing import Annotated
from dracon import Arg, DeferredNode, construct


class DatabaseConfig(BaseModel):
    """Configuration for the database connection."""

    host: str = 'localhost'
    port: int = 5432
    username: str  # Made required for the example
    password: str  # Made required for the example


class AppConfig(BaseModel):
    """Main application configuration model."""

    environment: Annotated[
        str, Arg(short='e', required=True, help="Deployment environment (dev, staging, prod).")
    ]
    log_level: Annotated[str, Arg(help="Logging level (e.g., INFO, DEBUG).")] = "INFO"
    workers: Annotated[int, Arg(help="Number of worker processes.")] = 1
    # Nested model, can be populated from YAML/CLI. Uses default_factory for Pydantic v2 best practice.
    database: Annotated[DatabaseConfig, Arg(help="Database configuration.")] = Field(
        default_factory=DatabaseConfig
    )
    # Output path depends on runtime context, marked as DeferredNode.
    output_path: Annotated[DeferredNode[str], Arg(help="Path for output files.")] = (
        "/tmp/dracon_output"  # Provide a default
    )

    def process_data(self):
        """Example method demonstrating use of the loaded configuration."""
        print("-" * 20)
        print(f"Processing for environment: {self.environment}")
        print(f"Using Database:")
        print(f"  Host: {self.database.host}")
        print(f"  Port: {self.database.port}")
        print(f"  User: {self.database.username}")
        # print(f"  Password: {'*' * len(self.database.password)}") # Avoid printing password
        print(f"Settings:")
        print(f"  Workers: {self.workers}")
        print(f"  Log Level: {self.log_level}")

        # The output_path is a DeferredNode. We need to call construct()
        # to get the final value, providing any necessary context.
        print("Constructing output path...")
        final_output = construct(
            self.output_path, context={'computed_runtime_value': self.generate_unique_id()}
        )
        print(f"  Output Path: {final_output}")
        print("-" * 20)

        # ... actual application logic would go here ...

    def generate_unique_id(self) -> str:
        """Example helper to generate a value based on current config state."""
        from time import time

        # In a real app, this might involve more complex logic or external calls
        return f"{self.environment}-{self.database.host}-{self.workers}-{int(time())}"
