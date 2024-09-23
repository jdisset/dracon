## {{{                          --     imports     --
from typing import Optional, Any
from copy import deepcopy
import re
from pydantic import BaseModel
from enum import Enum
from dracon.utils import dict_like, DictLike, ListLike
from dracon.composer import (
    MergeNode,
    CompositionResult,
    walk_node,
    DraconMappingNode,
    DraconSequenceNode,
    IncludeNode,
    InterpolableNode,
)
from ruamel.yaml.nodes import Node
from dracon.keypath import KeyPath
from dracon.merge import merged, MergeKey
from dracon.interpolation import evaluate_expression
from functools import partial
##────────────────────────────────────────────────────────────────────────────}}}


## {{{                      --     instruct utils     --


class Instruction:
    @staticmethod
    def match(value: Optional[str]) -> Optional['Instruction']:
        raise NotImplementedError

    def process(self, comp_res: CompositionResult, path: KeyPath):
        raise NotImplementedError


def add_to_context(context, node: Node):
    if isinstance(node, InterpolableNode):
        node.extra_symbols = merged(node.extra_symbols, context, MergeKey(raw='{<+}'))
    elif isinstance(node, IncludeNode):
        node.extra_symbols = merged(node.extra_symbols, context, MergeKey(raw='{<+}'))


def preprocess_comptime_ampreferences(self, match, comp_res, current_path):
    available_anchors = comp_res.anchor_paths
    context_str = ''
    # references can also have a list of variable definitions attached to them
    # syntax is ${&unique_id:var1=expr1,var2=expr2}
    if ':' in match.expr:
        match.expr, vardefs = match.expr.split(':')
        context_str = f'context=dict({vardefs})'

    match_parts = match.expr.split('.', 1)
    if match_parts[0] in available_anchors:  # we're matching an anchor
        keypath = available_anchors[match_parts[0]].copy()
        keypath = keypath.down(match_parts[1]) if len(match_parts) > 1 else keypath
    else:  # we're trying to match a keypath
        keypath = current_path.parent.down(KeyPath(match.expr))

    node = keypath.get_obj(comp_res.root)

    # newexpr = f'__DRACON_RESOLVABLES[{unique_id}].resolve({context_str})'

    return newexpr


def process_instructions(comp_res: CompositionResult):
    instruction_nodes = []

    def find_instruction_nodes(node: Node, path: KeyPath):
        if inst := match_instruct(node.tag):
            instruction_nodes.append((inst, path))

    comp_res.walk(find_instruction_nodes)
    instruction_nodes = sorted(instruction_nodes, key=lambda x: len(x[1]))

    for inst, path in instruction_nodes:
        inst.process(comp_res, path.copy())

    return comp_res


##────────────────────────────────────────────────────────────────────────────}}}
## {{{                          --     define     --
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
        parent_node = path.parent.get_obj(comp_res.root)
        assert isinstance(parent_node, DraconMappingNode)
        assert key_node.tag == '!define', f"Expected tag '!define', but got {key_node.tag}"

        value = value_node.value
        ctx = {}

        if isinstance(value_node, InterpolableNode):
            value = evaluate_expression(
                value,
                current_path=path,
                root_obj=comp_res.root,
                extra_symbols=value_node.extra_symbols,
            )
            ctx = merged(ctx, value_node.extra_symbols, MergeKey(raw='{<+}'))

        var_name = key_node.value
        assert var_name.isidentifier(), f"Invalid variable name in define instruction: {var_name}"

        ctx = merged(ctx, {var_name: deepcopy(value)}, MergeKey(raw='{<+}'))
        walk_node(
            node=parent_node,
            callback=partial(add_to_context, ctx),
        )

        # remove the node
        del parent_node[var_name]


##────────────────────────────────────────────────────────────────────────────}}}
## {{{                           --     each     --
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

        print(f"Processing !each at {path}")
        key_node = deepcopy(path.get_obj(comp_res.root))
        value_node = deepcopy(path.removed_mapping_key().get_obj(comp_res.root))

        parent_node = path.parent.get_obj(comp_res.root)
        assert isinstance(parent_node, DraconMappingNode)
        assert isinstance(
            key_node, InterpolableNode
        ), f"Expected an interpolable node for 'each' instruction, but got {key_node}"

        ctx = {}

        list_like = evaluate_expression(
            key_node.value,
            current_path=path,
            root_obj=comp_res.root,
            extra_symbols=key_node.extra_symbols,
        )
        ctx = merged(ctx, key_node.extra_symbols, MergeKey(raw='{<+}'))

        new_parent = deepcopy(parent_node)
        del new_parent[key_node.value]

        if isinstance(value_node, DraconSequenceNode):
            assert len(parent_node) == 1, "Cannot use !each with a sequence node in a mapping"
            new_parent = DraconSequenceNode.from_mapping(parent_node, empty=True)
            new_nodes = value_node.value
        elif isinstance(value_node, DraconMappingNode):
            new_nodes = value_node.value
        else:
            new_nodes = [value_node]

        for item in list_like:
            for node in new_nodes:
                new_node = deepcopy(node)
                new_parent.append(new_node)
                ctx = merged(ctx, {self.var_name: item}, MergeKey(raw='{<+}'))
                walk_node(
                    node=new_node,
                    callback=partial(add_to_context, ctx),
                )

        comp_res.replace_node_at(path.parent, new_parent)

        del parent_node[key_node.value]


##────────────────────────────────────────────────────────────────────────────}}}


AVAILABLE_INSTRUCTIONS = [Define, Each]


def match_instruct(value: str) -> Optional[Instruction]:
    matches = [inst.match(value) for inst in AVAILABLE_INSTRUCTIONS]
    for match in matches:
        if match:
            return match
    return None
