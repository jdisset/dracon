from .utils import *
from .merge import *
from .loader import *
from .composer import *
from .keypath import *


def load(config_path: str | Path, raw_dict=False, **kwargs):
    loader = DraconLoader()
    if raw_dict:
        loader.yaml.constructor.yaml_base_dict_type = dict
    return loader.load(config_path)

def loads(config_str: str, raw_dict=False, **kwargs):
    loader = DraconLoader()
    if raw_dict:
        loader.yaml.constructor.yaml_base_dict_type = dict
    return loader.loads(config_str)

def dump(data, stream=None, **kwargs):
    loader = DraconLoader()
    return loader.dump(data, stream)
