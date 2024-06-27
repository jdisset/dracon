from pathlib import Path
from typing import List, Optional, Dict, Any, Union
import re
import yaml
from pydantic import BaseModel
from dracon.utils import *
from dracon.merge import *
from dracon.loader import *
from dracon.composer import *
from dracon.keypath import *

# cfg = load_config_from_str(load_raw_conf_str('pkg:dracon:tests/configs/simple.yaml'))
# cfg = load_from_include_str('pkg:dracon:tests/configs/simple.yaml', '', None)
# cfg = load_from_pkg('dracon:tests/configs/simple.yaml')

# # dump using ruamel.yaml:
# from ruamel.yaml import YAML
# import io
# yaml = YAML()
# str_stream = io.StringIO()
# yaml.dump(cfg, str_stream)
# print(str_stream.getvalue())

