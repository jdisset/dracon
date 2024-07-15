from .utils import *
from .merge import *
from .loader import *
from .composer import *
from .keypath import *


def load(config_path: str | Path):
    loader = DraconLoader()
    return loader.load(config_path)

def dump(data, stream=None):
    loader = DraconLoader()
    return loader.dump(data, stream)
