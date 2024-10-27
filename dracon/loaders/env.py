import os
from typing import ForwardRef, TypeAlias, Optional

DraconLoader = ForwardRef('DraconLoader')


def read_from_env(path: str, loader: Optional[DraconLoader] = None):
    return str(os.getenv(path)), {}
