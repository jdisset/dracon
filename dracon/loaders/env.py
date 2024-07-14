import os
from typing import ForwardRef, TypeAlias

DraconLoader = ForwardRef('DraconLoader')

def read_from_env(path: str):
    return str(os.getenv(path))

def compose_from_env(path: str, loader: DraconLoader):
    return loader.compose_config_from_str(read_from_env(path))

