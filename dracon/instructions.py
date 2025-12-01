# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

## {{{                          --     imports     --
from typing import Optional, Any
import re
import time
from pydantic import BaseModel
from enum import Enum
from dracon.utils import dict_like, DictLike, ListLike, ftrace, deepcopy, node_repr, ser_debug
from dracon.composer import (
    CompositionResult,
    walk_node,
    DraconMappingNode,
    DraconSequenceNode,
    IncludeNode,
)
from dracon.utils import ShallowDict
from ruamel.yaml.nodes import Node
from dracon.keypath import KeyPath, ROOTPATH, KeyPathToken, MAPPING_KEY
from dracon.merge import merged, MergeKey, add_to_context
from dracon.interpolation import evaluate_expression, InterpolableNode
from dracon.deferred import DeferredNode, make_deferred
from functools import partial
from dracon.nodes import DraconScalarNode
import logging

logger = logging.getLogger(__name__)

##────────────────────────────────────────────────────────────────────────────}}}

## {{{                      --     instruct utils     --


class Instruction:
    @staticmethod
    def match(value: Optional[str]) -> Optional['Instruction']:
        raise NotImplementedError

    def process(self, comp_res: CompositionResult, path: KeyPath, loader) -> CompositionResult:
        raise NotImplementedError


@ftrace()
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
                engine=loader.interpolation_engine,
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

    @ftrace(watch=[])
    def process(self, comp_res: CompositionResult, path: KeyPath, loader):
        var_name, value, parent_node = self.get_name_and_value(comp_res, path, loader)

        walk_node(
            node=parent_node,
            callback=partial(add_to_context, {var_name: value}),
        )

        comp_res.defined_vars[var_name] = value

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

    @ftrace(watch=[])
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

    Duplicate the value node for each item in the list-like node and assign the item 
    to the variable var_name (which is added to the context).
    
    If list-like-expr is an interpolation, this node triggers its composition-time evaluation.

    For sequence values:
        !each(i) ${range(3)}:
            - value_${i}
    
    For mapping values with dynamic keys:
        !each(i) ${range(3)}:
            key_${i}: value_${i}

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

        base_key_node = path.get_obj(comp_res.root)
        base_value_node = path.removed_mapping_key().get_obj(comp_res.root)

        key_node = base_key_node
        value_node = base_value_node

        parent_node = path.parent.get_obj(comp_res.root)

        assert isinstance(parent_node, DraconMappingNode)
        assert isinstance(
            key_node, InterpolableNode
        ), f"Expected an interpolable node for 'each' instruction, but got {key_node}, a {type(key_node)}"

        list_like = evaluate_expression(
            key_node.value,
            current_path=path,
            root_obj=comp_res.root,
            engine=loader.interpolation_engine,
            context=key_node.context,
        )

        logger.debug(
            f"Processing each instruction, key_node.context.{self.var_name}={key_node.context.get(self.var_name)}"
        )

        # remove the original each instruction node
        new_parent = parent_node.copy()
        del new_parent[key_node.value]

        mkey = MergeKey(raw='{<~}[~<]')
        # Handle sequence values
        if isinstance(value_node, DraconSequenceNode):
            assert len(parent_node) == 1, "Cannot use !each with a sequence node in a mapping"
            new_parent = DraconSequenceNode.from_mapping(parent_node, empty=True)
            logger.debug(f"Processing an each instruction with a sequence node. {list_like=}")

            for item in list_like:
                logger.debug(f"  each: {item=}")
                item_ctx = ShallowDict({self.var_name: item})
                logger.debug(
                    f"  after merge into key_node.ctx, item_ctx.{self.var_name}={item_ctx.get(self.var_name)}"
                )
                for node in value_node.value:
                    if isinstance(node, DeferredNode):
                        new_value_node = node.copy(deepcopy_composition=False)
                    else:
                        new_value_node = deepcopy(node)

                    walk_node(
                        node=new_value_node,
                        callback=partial(add_to_context, item_ctx, merge_key=mkey),
                    )

                    new_parent.append(new_value_node)

        # Handle mapping values
        elif isinstance(value_node, DraconMappingNode):
            logger.debug(f"Processing an each instruction with a dict node. {list_like=}")

            # check if the mapping contains exactly one key that is an instruction
            # if so, we need to handle nesting specially by wrapping in a sequence
            value_items = list(value_node.items())
            has_single_instruction_child = (
                len(value_items) == 1 and match_instruct(value_items[0][0].tag)
            )

            if has_single_instruction_child:
                # the only child is an instruction - we need to process each iteration
                # with proper context, then immediately process the nested instruction
                inner_knode, inner_vnode = value_items[0]
                inner_inst = match_instruct(inner_knode.tag)

                # collect all results first, then determine the output type
                all_results = []

                for item in list_like:
                    item_ctx = merged(key_node.context, {self.var_name: item}, MergeKey(raw='{<~}'))
                    new_inner_vnode = deepcopy(inner_vnode)
                    new_inner_knode = deepcopy(inner_knode)
                    add_to_context(item_ctx, new_inner_knode, mkey)
                    walk_node(
                        node=new_inner_vnode,
                        callback=partial(add_to_context, item_ctx, merge_key=mkey),
                    )
                    # create a temporary composition with just this instruction
                    # and process it immediately
                    temp_mapping = DraconMappingNode(
                        tag='tag:yaml.org,2002:map',
                        value=[(new_inner_knode, new_inner_vnode)]
                    )
                    temp_comp = CompositionResult(root=temp_mapping)
                    temp_path = KeyPath([KeyPathToken.ROOT, MAPPING_KEY, new_inner_knode.value])
                    temp_comp = inner_inst.process(temp_comp, temp_path, loader)
                    all_results.append(temp_comp.root)

                # determine result type from first result and merge all
                if all_results and isinstance(all_results[0], DraconSequenceNode):
                    new_parent = DraconSequenceNode.from_mapping(parent_node, empty=True)
                    for result in all_results:
                        for elem in result.value:
                            new_parent.append(elem)
                else:
                    new_parent = parent_node.copy()
                    new_parent.value = []
                    for result in all_results:
                        for k, v in result.items():
                            new_parent.append((k, v))
            else:
                for item in list_like:
                    item_ctx = merged(key_node.context, {self.var_name: item}, MergeKey(raw='{<~}'))
                    for knode, vnode in value_node.items():
                        new_vnode = deepcopy(vnode)
                        new_knode = deepcopy(knode)

                        # check if this key is itself an instruction (e.g. nested !each)
                        # if so, don't evaluate it - just propagate context and let the
                        # instruction processor handle it in a subsequent pass
                        if match_instruct(new_knode.tag):
                            add_to_context(item_ctx, new_knode, mkey)
                            walk_node(
                                node=new_vnode,
                                callback=partial(add_to_context, item_ctx, merge_key=mkey),
                            )
                            new_parent.append((new_knode, new_vnode))
                            continue

                        # can't add the knode directly to the new_parent, as that would result in duplicate keys
                        # we need to evaluate the key node first
                        assert isinstance(
                            knode, InterpolableNode
                        ), f"Keys inside an !each instruction must be interpolable (so that they're unique), but got {knode}"
                        add_to_context(item_ctx, new_knode, mkey)
                        scalar_knode = DraconScalarNode(
                            tag=new_knode.tag,
                            value=new_knode.evaluate(
                                engine=loader.interpolation_engine,
                                context=item_ctx,
                            ),
                        )
                        new_parent.append((scalar_knode, new_vnode))
                        walk_node(
                            node=new_vnode,
                            callback=partial(add_to_context, item_ctx, merge_key=mkey),
                        )

        else:
            raise ValueError(
                f"Invalid value node for 'each' instruction: {value_node} of type {type(value_node)}"
            )

        # del parent_node[key_node.value]
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
    `!if expr : value`  (shorthand for then-only)
    `!if expr :
      then: value_if_true
      else: value_if_false`

    Evaluate the truthiness of expr (if it's an interpolation, it evaluates it).
    
    If then/else keys are present:
    - If truthy, use the 'then' branch value
    - If falsy, use the 'else' branch value (or remove if no else)
    
    If no then/else keys (shorthand):
    - If truthy, include the content
    - If falsy, remove the entire node
    """

    @staticmethod
    def match(value: Optional[str]) -> Optional['If']:
        if not value:
            return None
        if value == '!if':
            return If()
        return None

    def _get_then_else_nodes(self, value_node):
        """Extract then/else nodes, returns (then_node, else_node, is_then_else_style)"""
        if not isinstance(value_node, DraconMappingNode):
            return None, None, False
            
        keys = [k.value for k, _ in value_node.items()]
        if 'then' in keys or 'else' in keys:
            then_node = else_node = None
            for k, v in value_node.items():
                if k.value == 'then':
                    then_node = v
                elif k.value == 'else':
                    else_node = v
            return then_node, else_node, True
        return None, None, False

    def _add_content_to_parent(self, parent_node, content_node, comp_res, parent_path):
        """Add content node to parent, handling different node types"""
        if isinstance(content_node, DraconMappingNode):
            for key, node in content_node.items():
                parent_node.append((key, node))
        elif isinstance(content_node, DraconSequenceNode):
            raise NotImplementedError("if statement containing a sequence is not yet implemented")
        else:
            # scalar node - replace parent entirely
            assert isinstance(parent_node, DraconMappingNode), 'if statement with scalar-like must appear in a mapping'
            comp_res.set_at(parent_path, content_node)

    @ftrace(watch=[])
    def process(self, comp_res: CompositionResult, path: KeyPath, loader):
        if not path.is_mapping_key():
            raise ValueError(f"instruction 'if' must be a key, but got {path}")

        value_path = path.removed_mapping_key()
        parent_path = path.parent

        key_node = path.get_obj(comp_res.root)
        value_node = value_path.get_obj(comp_res.root)
        parent_node = parent_path.get_obj(comp_res.root)

        assert key_node.tag == '!if', f"Expected tag '!if', but got {key_node.tag}"

        # evaluate condition
        if isinstance(key_node, InterpolableNode):
            from dracon.merge import merged, MergeKey
            eval_context = merged(key_node.context or {}, loader.context or {}, MergeKey(raw='{<+}'))
            result = evaluate_expression(
                key_node.value, path, comp_res.root, engine=loader.interpolation_engine, context=eval_context
            )
            condition = bool(result)
        else:
            condition = as_bool(key_node.value)

        # check for then/else pattern
        then_node, else_node, is_then_else = self._get_then_else_nodes(value_node)
        
        if is_then_else:
            # then/else format
            selected_node = then_node if condition else else_node
            if selected_node is not None:
                self._add_content_to_parent(parent_node, selected_node, comp_res, parent_path)
        else:
            # shorthand format - include content if condition is true
            if condition:
                self._add_content_to_parent(parent_node, value_node, comp_res, parent_path)

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
