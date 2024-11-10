## {{{                          --     imports     --
from typing import Optional, Any
import re
from pydantic import BaseModel
from enum import Enum
from dracon.utils import dict_like, DictLike, ListLike, ftrace, deepcopy
from dracon.composer import (
    CompositionResult,
    walk_node,
    DraconMappingNode,
    DraconSequenceNode,
    IncludeNode,
)
from ruamel.yaml.nodes import Node
from dracon.keypath import KeyPath, ROOTPATH
from dracon.merge import merged, MergeKey, add_to_context
from dracon.interpolation import evaluate_expression, InterpolableNode
from functools import partial

##────────────────────────────────────────────────────────────────────────────}}}

## {{{                      --     instruct utils     --


class Instruction:
    @staticmethod
    def match(value: Optional[str]) -> Optional['Instruction']:
        raise NotImplementedError

    def process(self, comp_res: CompositionResult, path: KeyPath, loader) -> CompositionResult:
        raise NotImplementedError


@ftrace(watch=[])
def process_instructions(comp_res: CompositionResult, loader) -> CompositionResult:
    # then all other instructions
    instruction_nodes = []
    seen_paths = set()

    def find_instruction_nodes(node: Node, path: KeyPath):
        nonlocal instruction_nodes
        nonlocal seen_paths
        if hasattr(node, 'tag') and node.tag:
            if (path not in seen_paths) and (inst := match_instruct(node.tag)):
                instruction_nodes.append((inst, path))

    def refresh_instruction_nodes():
        nonlocal instruction_nodes
        instruction_nodes = []
        comp_res.make_map()
        comp_res.walk(find_instruction_nodes)
        instruction_nodes = sorted(instruction_nodes, key=lambda x: len(x[1]))

    refresh_instruction_nodes()

    while instruction_nodes:
        inst, path = instruction_nodes.pop(0)
        assert path not in seen_paths, f"Instruction {inst} at {path} already processed"
        seen_paths.add(path)
        comp_res = inst.process(comp_res, path.copy(), loader)
        refresh_instruction_nodes()

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

    def get_name_and_value(self, comp_res, path, loader):
        if not path.is_mapping_key():
            raise ValueError(
                f"instruction {self.__class__.__name__} must be a mapping key, but got {path}"
            )
        key_node = path.get_obj(comp_res.root)
        value_node = path.removed_mapping_key().get_obj(comp_res.root)
        parent_node = path.parent.get_obj(comp_res.root)
        assert isinstance(parent_node, DraconMappingNode)

        if isinstance(value_node, InterpolableNode):
            value = evaluate_expression(
                value_node.value,
                current_path=path,
                root_obj=comp_res.root,
                context=value_node.context,
            )
        else:
            value = loader.load_composition_result(CompositionResult(root=value_node))

        var_name = key_node.value
        assert (
            var_name.isidentifier()
        ), f"Invalid variable name in {self.__class__.__name__} instruction: {var_name}"

        del parent_node[var_name]

        return var_name, value, parent_node

    @ftrace(False, watch=[])
    def process(self, comp_res: CompositionResult, path: KeyPath, loader):
        var_name, value, parent_node = self.get_name_and_value(comp_res, path, loader)

        walk_node(
            node=parent_node,
            callback=partial(add_to_context, {var_name: value}),
        )

        return comp_res


class SetDefault(Define):
    """
    `!set_default var_name : default_value`

    Similar to !define, but only sets the variable if it doesn't already exist in the context

    If value is an interpolation, this node triggers composition-time evaluation
    """

    @staticmethod
    def match(value: Optional[str]) -> Optional['SetDefault']:
        if not value:
            return None
        if value == '!set_default':
            return SetDefault()
        return None

    @ftrace(False, watch=[])
    def process(self, comp_res: CompositionResult, path: KeyPath, loader):
        var_name, value, parent_node = self.get_name_and_value(comp_res, path, loader)

        walk_node(
            node=parent_node,
            callback=partial(
                add_to_context, {var_name: value}, merge_key=MergeKey(raw='<<{>~}[>~]')
            ),
        )

        return comp_res


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

    @ftrace(inputs=False, watch=[])
    def process(self, comp_res: CompositionResult, path: KeyPath, loader):
        if not path.is_mapping_key():
            raise ValueError(f"instruction 'each' must be a mapping key, but got {path}")

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
            context=key_node.context,
        )

        ctx = merged(ctx, key_node.context, MergeKey(raw='{<+}'))

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

        del parent_node[key_node.value]
        comp_res.set_at(path.parent, new_parent)

        return comp_res


##────────────────────────────────────────────────────────────────────────────}}}
## {{{                            --     if     --


def as_bool(value: str | int | bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        try:
            return bool(int(value))
        except ValueError:
            pass
        if value.lower() in ['true']:
            return True
        if value.lower() in ['false', 'null', 'none', '']:
            return False
    raise ValueError(f"Could not convert {value} to bool")


class If(Instruction):
    """
    `!if expr : value`

    Evaluate the truthiness of expr (if it's an interpolation, it evaluates it).
    If truthy, then value replaces this entire node.
    If falsy, then the entire node is removed.
    """

    @staticmethod
    def match(value: Optional[str]) -> Optional['If']:
        if not value:
            return None
        if value == '!if':
            return If()
        return None

    @ftrace(False, watch=[])
    def process(self, comp_res: CompositionResult, path: KeyPath, loader):
        if not path.is_mapping_key():
            raise ValueError(f"instruction 'if' must be a key, but got {path}")

        value_path = path.removed_mapping_key()
        parent_path = path.parent

        key_node = path.get_obj(comp_res.root)
        value_node = value_path.get_obj(comp_res.root)
        parent_node = parent_path.get_obj(comp_res.root)

        assert key_node.tag == '!if', f"Expected tag '!if', but got {key_node.tag}"

        expr = key_node.value

        if isinstance(key_node, InterpolableNode):
            evaluated_expr = bool(
                evaluate_expression(
                    expr,
                    current_path=path,
                    root_obj=comp_res.root,
                    context=key_node.context,
                )
            )
        else:
            evaluated_expr = as_bool(expr)

        if evaluated_expr:
            if isinstance(value_node, DraconMappingNode):
                assert isinstance(
                    parent_node, DraconMappingNode
                ), 'if statement with mapping must appear in a mapping'
                for key, node in value_node.items():
                    parent_node.append((key, node))
            elif isinstance(value_node, DraconSequenceNode):
                raise NotImplementedError(
                    "if statement containing a sequence is not yet implemented"
                )
            else:
                assert isinstance(
                    parent_node, DraconMappingNode
                ), 'if statement with scalar-like must appear in a mapping'
                comp_res.set_at(parent_path, value_node)

        del parent_node[key_node.value]
        return comp_res


##────────────────────────────────────────────────────────────────────────────}}}

AVAILABLE_INSTRUCTIONS = [SetDefault, Define, Each, If]


def match_instruct(value: str) -> Optional[Instruction]:
    matches = [inst.match(value) for inst in AVAILABLE_INSTRUCTIONS]
    # need to refresh
    for match in matches:
        if match:
            return match
    return None
