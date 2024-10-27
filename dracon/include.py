## {{{                          --     imports     --
from ruamel.yaml import YAML, Node
from typing import Type, Callable
import copy
import os

# for cache stuff:
from cachetools import cached, LRUCache
from cachetools.keys import hashkey
from functools import lru_cache
import re
from pathlib import Path
from typing import Optional, Dict, Any, Annotated, TypeVar
from pydantic import BeforeValidator, Field, PlainSerializer

from dracon.composer import (
    IncludeNode,
    CompositionResult,
    DraconComposer,
    delete_unset_nodes,
    walk_node,
)

from dracon.draconstructor import Draconstructor
from dracon.keypath import KeyPath, ROOTPATH

from dracon.utils import (
    DictLike,
    MetadataDictLike,
    ListLike,
    ShallowDict,
    ftrace,
    deepcopy,
)
from dracon.interpolation_utils import resolve_interpolable_variables
from dracon.interpolation import InterpolableNode
from dracon.merge import process_merges, add_to_context, merged, MergeKey
from dracon.instructions import process_instructions
from dracon.loaders.file import read_from_file
from dracon.loaders.pkg import read_from_pkg
from dracon.deferred import DeferredNode, process_deferred
from dracon.loaders.env import read_from_env
from dracon.representer import DraconRepresenter

from dracon.postprocess import preprocess_references

from dracon import dracontainer
from functools import partial


##────────────────────────────────────────────────────────────────────────────}}}
