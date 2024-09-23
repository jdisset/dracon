from typing import Optional, Any
from copy import deepcopy
import re
from pydantic import BaseModel
from enum import Enum
from dracon.utils import dict_like, DictLike, ListLike
from dracon.composer import (
    MergeNode,
    CompositionResult,
    DraconMappingNode,
    DraconSequenceNode,
    InterpolableNode,
)
from ruamel.yaml.nodes import Node
from dracon.keypath import KeyPath


class Instruction:
    @staticmethod
    def match(value: Optional[str]) -> Optional['Instruction']:
        raise NotImplementedError

    def process(self, comp_res: CompositionResult, path: KeyPath):
        raise NotImplementedError


class Define(Instruction):
    """
    `!define var_name : value`

    Define a variable var_name with the value of the node
    and add it to the parent node's context
    The node is then removed from the parent node
    (if you want to define and keep the node, use !define_keep)

    If value is an interpolation, this node triggers composition-time evaluation
    """

    @staticmethod
    def match(value: Optional[str]) -> Optional['Define']:
        if not value:
            return None
        if value == '!define':
            return Define()
        return None

    def process(self, comp_res: CompositionResult, path: KeyPath):
        if not path.is_mapping_key():
            raise ValueError(f"instruction 'define' must be a mapping key, but got {path}")

        key_node = path.get_obj(comp_res.root)
        value_node = path.removed_mapping_key().get_obj(comp_res.root)

        if isinstance(key_node, InterpolableNode):
            key_node = key_node.compose(comp_res.context)
            


class Each(Instruction):
    PATTERN = r"!each\(([a-zA-Z_]\w*)\)"

    """
    `!each(var_name) list-like-expr : value`

    Duplicate the value node for each item in the list-like node
    and assign the item to the variable var_name (which is added to the context)

    If list-like-expr is an interpolation, this node triggers its composition-time evaluation.


    Removed from final composition.
    """

    def __init__(self, var_name: str):
        self.var_name = var_name

    @staticmethod
    def match(value: Optional[str]) -> Optional['Each']:
        if not value:
            return None
        match = re.match(Each.PATTERN, value)
        if match:
            var_name = match.group(1)
            return Each(var_name)
        return None

    def process(self, comp_res: CompositionResult, path: KeyPath):
        if not path.is_mapping_key():
            raise ValueError(f"instruction 'each' must be a mapping key, but got {path}")

        key_node = path.get_obj(comp_res.root)
        value_node = path.removed_mapping_key().get_obj(comp_res.root)

        # TODO: implement the actual processing. duplicate value_node for each item in key_node
        ...


AVAILABLE_INSTRUCTIONS = [Define, Each]


def match_instruct(value: str) -> Optional[Instruction]:
    matches = [inst.match(value) for inst in AVAILABLE_INSTRUCTIONS]
    for match in matches:
        if match:
            return match
    return None


def process_instructions(comp_res: CompositionResult):
    instruction_nodes = []

    def find_instruction_nodes(node: Node, path: KeyPath):
        if inst := match_instruct(node.tag):
            instruction_nodes.append((inst, path))
            node.tag = ''

    comp_res.walk(find_instruction_nodes)

    for inst, path in instruction_nodes:
        inst.process(comp_res, path.copy())

    return comp_res
