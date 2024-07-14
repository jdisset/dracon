import os
from typing import ForwardRef, TypeAlias

DraconLoader = ForwardRef('DraconLoader')

def compose_from_env(path: str, loader: DraconLoader):
    return loader.compose_config_from_str(str(os.getenv(path)))

