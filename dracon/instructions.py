# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

## {{{                          --     imports     --
from typing import Optional
import re
from dracon.utils import ftrace, deepcopy
from dracon.composer import (
    CompositionResult,
    walk_node,
    DraconMappingNode,
    DraconSequenceNode,
)
from dracon.utils import ShallowDict, values_equal
from ruamel.yaml.nodes import Node
from dracon.keypath import KeyPath, KeyPathToken, MAPPING_KEY
from dracon.nodes import node_source
from dracon.merge import merged, MergeKey, cached_merge_key, add_to_context
from dracon.interpolation import evaluate_expression, InterpolableNode
from dracon.deferred import DeferredNode
from functools import partial
from dracon.nodes import DraconScalarNode
import logging

logger = logging.getLogger(__name__)

##────────────────────────────────────────────────────────────────────────────}}}

## {{{                      --     instruct utils     --


def evaluate_nested_mapping_keys(node, engine, context):
    if isinstance(node, DraconMappingNode):
        new_items = []
        for k_node, v_node in node.value:
            # Evaluate the key if it's an InterpolableNode
            if isinstance(k_node, InterpolableNode):
                scalar_key = DraconScalarNode(
                    tag=k_node.tag,
                    value=k_node.evaluate(engine=engine, context=context),
                )
                new_items.append((scalar_key, v_node))
            else:
                new_items.append((k_node, v_node))
            evaluate_nested_mapping_keys(v_node, engine, context)
        node.value = new_items
    elif isinstance(node, DraconSequenceNode):
        for item in node.value:
            evaluate_nested_mapping_keys(item, engine, context)


class Instruction:
    @staticmethod
    def match(value: Optional[str]) -> Optional['Instruction']:
        raise NotImplementedError

    def process(self, comp_res: CompositionResult, path: KeyPath, loader) -> CompositionResult:
        raise NotImplementedError


@ftrace()
def process_instructions(comp_res: CompositionResult, loader) -> CompositionResult:
    instruction_nodes = []
    seen_paths = set()

    def find_instruction_nodes(node: Node, path: KeyPath):
        nonlocal instruction_nodes
        nonlocal seen_paths
        tag = getattr(node, 'tag', None)
        if tag:
            if (path not in seen_paths) and (inst := match_instruct(tag)):
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
        from dracon.diagnostics import CompositionError
        if not path.is_mapping_key():
            raise CompositionError(
                f"!{self.__class__.__name__.lower()} must be a mapping key, got {path}"
            )
        key_node = path.get_obj(comp_res.root)
        value_node = path.removed_mapping_key().get_obj(comp_res.root)
        parent_node = path.parent.get_obj(comp_res.root)
        if not isinstance(parent_node, DraconMappingNode):
            ctx = node_source(key_node)
            raise CompositionError(
                f"!{self.__class__.__name__.lower()} parent must be a mapping, got {type(parent_node).__name__}",
                context=ctx,
            )

        if isinstance(value_node, InterpolableNode):
            value = evaluate_expression(
                value_node.value,
                current_path=path,
                root_obj=comp_res.root,
                engine=loader.interpolation_engine,
                context=value_node.context,
                source_context=value_node.source_context,
            )
        else:
            value = loader.load_composition_result(CompositionResult(root=value_node))

        var_name = key_node.value
        if not var_name.isidentifier():
            ctx = node_source(key_node)
            raise CompositionError(
                f"Invalid variable name '{var_name}' in !{self.__class__.__name__.lower()}. Must be a valid Python identifier.",
                context=ctx,
            )

        del parent_node[str(path[-1])]

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

        # mark as accessed for usage tracking when the variable already exists
        if var_name in loader.context:
            _ = loader.context[var_name]

        walk_node(
            node=parent_node,
            callback=partial(
                add_to_context, {var_name: value}, merge_key=cached_merge_key('<<{>~}[>~]')
            ),
        )

        comp_res.defined_vars.setdefault(var_name, value)
        if var_name not in comp_res.defined_vars or values_equal(comp_res.defined_vars[var_name], value):
            comp_res.default_vars.add(var_name)

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

    def _generate_sequence_items(self, list_like, value_node, key_node, mkey):
        """Generate expanded sequence items from !each iteration."""
        result = []
        for item in list_like:
            item_ctx = ShallowDict({self.var_name: item})
            for node in value_node.value:
                if isinstance(node, DeferredNode):
                    new_value_node = node.copy(deepcopy_composition=False)
                else:
                    new_value_node = deepcopy(node)
                walk_node(
                    node=new_value_node,
                    callback=partial(add_to_context, item_ctx, merge_key=mkey),
                )
                result.append(new_value_node)
        return result

    @staticmethod
    def _all_each_with_seq_values(parent_node):
        """True iff every key in parent is an !each instruction with a sequence value."""
        if len(parent_node) == 0:
            return False
        for k, v in parent_node.items():
            tag = getattr(k, 'tag', None)
            if not tag:
                return False
            inst = match_instruct(str(tag) if not isinstance(tag, str) else tag)
            if not isinstance(inst, Each) or not isinstance(v, DraconSequenceNode):
                return False
        return True

    def _expand_all_each_siblings(self, parent_node, current_key_node, current_list_like,
                                  comp_res, path, loader, mkey):
        """Batch-expand all !each siblings with sequence values, in mapping order."""
        all_expanded = []
        for k_node, v_node in parent_node.items():
            if k_node is current_key_node:
                each_inst = self
                list_like = current_list_like
            else:
                tag_str = str(k_node.tag) if not isinstance(k_node.tag, str) else k_node.tag
                each_inst = Each.match(tag_str)
                list_like = evaluate_expression(
                    k_node.value,
                    current_path=path,
                    root_obj=comp_res.root,
                    engine=loader.interpolation_engine,
                    context=k_node.context,
                    source_context=k_node.source_context,
                )
            all_expanded.extend(each_inst._generate_sequence_items(list_like, v_node, k_node, mkey))
        return all_expanded

    def _is_inside_sequence(self, comp_res, path):
        """Check if this !each's parent mapping is an item inside a sequence."""
        parent_path = path.parent
        if len(parent_path) < 2:
            return False, None, None
        grandparent_path = parent_path.parent
        try:
            grandparent = grandparent_path.get_obj(comp_res.root)
            if isinstance(grandparent, DraconSequenceNode):
                idx = int(parent_path[-1])
                return True, grandparent, idx
        except (KeyError, ValueError, IndexError):
            pass
        return False, None, None

    @ftrace(inputs=False, watch=[])
    def process(self, comp_res: CompositionResult, path: KeyPath, loader):
        from dracon.diagnostics import CompositionError
        if not path.is_mapping_key():
            raise CompositionError(f"!each must be a mapping key, got {path}")

        key_node = path.get_obj(comp_res.root)
        value_node = path.removed_mapping_key().get_obj(comp_res.root)
        parent_node = path.parent.get_obj(comp_res.root)

        if not isinstance(parent_node, DraconMappingNode):
            ctx = node_source(key_node)
            raise CompositionError(f"!each parent must be a mapping, got {type(parent_node).__name__}", context=ctx)
        if not isinstance(key_node, InterpolableNode):
            ctx = node_source(key_node)
            raise CompositionError(
                f"!each key must contain an interpolation expression like ${{list}}, got '{key_node.value}'",
                context=ctx,
        )

        list_like = evaluate_expression(
            key_node.value,
            current_path=path,
            root_obj=comp_res.root,
            engine=loader.interpolation_engine,
            context=key_node.context,
            source_context=key_node.source_context,
        )

        mkey = cached_merge_key('{<~}[~<]')

        in_sequence, grandparent, seq_idx = self._is_inside_sequence(comp_res, path)
        all_each_seq = self._all_each_with_seq_values(parent_node)

        # auto-splice: all-!each-seq mapping inside a sequence
        if in_sequence and all_each_seq:
            expanded = self._expand_all_each_siblings(
                parent_node, key_node, list_like, comp_res, path, loader, mkey
            )
            new_value = grandparent.value[:seq_idx] + expanded + grandparent.value[seq_idx + 1 :]
            new_grandparent = DraconSequenceNode(
                tag=grandparent.tag,
                value=new_value,
                start_mark=grandparent.start_mark,
                end_mark=grandparent.end_mark,
                flow_style=grandparent.flow_style,
                comment=grandparent.comment,
                anchor=grandparent.anchor,
            )
            comp_res.set_at(path.parent.parent, new_grandparent)
            return comp_res

        if isinstance(value_node, DraconSequenceNode):
            # all sibling keys must also be !each with sequence values
            if not all_each_seq:
                ctx = node_source(key_node)
                raise CompositionError(
                    "!each with sequence value must be the only key in its mapping "
                    "(or all keys must be !each with sequence values)",
                    context=ctx,
                )
            expanded = self._expand_all_each_siblings(
                parent_node, key_node, list_like, comp_res, path, loader, mkey
            )
            new_parent = DraconSequenceNode.from_mapping(parent_node, empty=True)
            for node in expanded:
                new_parent.append(node)

        elif isinstance(value_node, DraconMappingNode):
            new_parent = parent_node.copy()
            del new_parent[key_node.value]
            value_items = list(value_node.items())
            has_single_instruction_child = len(value_items) == 1 and match_instruct(
                value_items[0][0].tag
            )

            if has_single_instruction_child:
                inner_knode, inner_vnode = value_items[0]
                inner_inst = match_instruct(inner_knode.tag)
                all_results = []

                for item in list_like:
                    item_ctx = merged(key_node.context, {self.var_name: item}, cached_merge_key('{<~}'))
                    new_inner_vnode = deepcopy(inner_vnode)
                    new_inner_knode = deepcopy(inner_knode)
                    add_to_context(item_ctx, new_inner_knode, mkey)
                    walk_node(
                        node=new_inner_vnode,
                        callback=partial(add_to_context, item_ctx, merge_key=mkey),
                    )
                    temp_mapping = DraconMappingNode(
                        tag='tag:yaml.org,2002:map', value=[(new_inner_knode, new_inner_vnode)]
                    )
                    temp_comp = CompositionResult(root=temp_mapping)
                    temp_path = KeyPath([KeyPathToken.ROOT, MAPPING_KEY, new_inner_knode.value])
                    temp_comp = inner_inst.process(temp_comp, temp_path, loader)
                    all_results.append(temp_comp.root)

                if all_results and isinstance(all_results[0], DraconSequenceNode):
                    expanded = []
                    for result in all_results:
                        expanded.extend(result.value)
                    # Check for auto-splice (parent is single-key mapping inside sequence)
                    if in_sequence and len(parent_node) == 1:
                        new_value = (
                            grandparent.value[:seq_idx]
                            + expanded
                            + grandparent.value[seq_idx + 1 :]
                        )
                        new_grandparent = DraconSequenceNode(
                            tag=grandparent.tag,
                            value=new_value,
                            start_mark=grandparent.start_mark,
                            end_mark=grandparent.end_mark,
                            flow_style=grandparent.flow_style,
                            comment=grandparent.comment,
                            anchor=grandparent.anchor,
                        )
                        comp_res.set_at(path.parent.parent, new_grandparent)
                        return comp_res
                    new_parent = DraconSequenceNode.from_mapping(parent_node, empty=True)
                    for elem in expanded:
                        new_parent.append(elem)
                else:
                    new_parent = parent_node.copy()
                    new_parent.value = []
                    for result in all_results:
                        for k, v in result.items():
                            new_parent.append((k, v))
            else:
                for item in list_like:
                    item_ctx = merged(key_node.context, {self.var_name: item}, cached_merge_key('{<~}'))
                    for knode, vnode in value_node.items():
                        new_vnode = deepcopy(vnode)
                        new_knode = deepcopy(knode)

                        if match_instruct(new_knode.tag):
                            add_to_context(item_ctx, new_knode, mkey)
                            walk_node(
                                node=new_vnode,
                                callback=partial(add_to_context, item_ctx, merge_key=mkey),
                            )
                            new_parent.append((new_knode, new_vnode))
                            continue

                        assert isinstance(knode, InterpolableNode), (
                            f"Keys inside an !each instruction must be interpolable (so that they're unique), but got {knode}"
                        )
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
                        evaluate_nested_mapping_keys(new_vnode, loader.interpolation_engine, item_ctx)
        else:
            raise ValueError(
                f"Invalid value node for 'each' instruction: {value_node} of type {type(value_node)}"
            )

        comp_res.set_at(path.parent, new_parent)

        # record each expansion trace
        if comp_res.trace is not None:
            from dracon.loader import _record_subtree_trace
            _record_subtree_trace(
                comp_res, path.parent,
                via="each_expansion",
                detail=f"!each({self.var_name})",
            )

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
            comp_res.set_at(parent_path, content_node)
        else:
            # scalar node - replace parent entirely
            if not isinstance(parent_node, DraconMappingNode):
                from dracon.diagnostics import CompositionError
                raise CompositionError("!if with scalar result must appear inside a mapping")
            comp_res.set_at(parent_path, content_node)

    @ftrace(watch=[])
    def process(self, comp_res: CompositionResult, path: KeyPath, loader):
        from dracon.diagnostics import CompositionError
        if not path.is_mapping_key():
            raise CompositionError(f"!if must be a mapping key, got {path}")

        value_path = path.removed_mapping_key()
        parent_path = path.parent

        key_node = path.get_obj(comp_res.root)
        value_node = value_path.get_obj(comp_res.root)
        parent_node = parent_path.get_obj(comp_res.root)

        if key_node.tag != '!if':
            raise CompositionError(f"Expected tag '!if', got '{key_node.tag}'")

        # evaluate condition
        if isinstance(key_node, InterpolableNode):
            from dracon.merge import merged, MergeKey

            eval_context = merged(
                key_node.context or {}, loader.context or {}, cached_merge_key('{<+}')
            )
            result = evaluate_expression(
                key_node.value,
                path,
                comp_res.root,
                engine=loader.interpolation_engine,
                context=eval_context,
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

        # record if-branch trace
        if comp_res.trace is not None:
            branch = "then" if condition else "else"
            condition_str = key_node.value
            from dracon.composition_trace import keypath_to_dotted
            from dracon.loader import _record_subtree_trace
            _record_subtree_trace(
                comp_res, parent_path,
                via="if_branch",
                detail=f"!if {branch} ({condition_str})",
            )

        return comp_res


##────────────────────────────────────────────────────────────────────────────}}}

AVAILABLE_INSTRUCTIONS = [SetDefault, Define, Each, If]


def match_instruct(value) -> Optional[Instruction]:
    # convert Tag to str once (avoids repeated Tag.__str__ in each match)
    value = str(value) if not isinstance(value, str) else value
    for inst in AVAILABLE_INSTRUCTIONS:
        match = inst.match(value)
        if match:
            return match
    # check if stripping a trailing colon would match — common YAML syntax mistake
    # e.g. `!set_default: a: null` parses the tag as `!set_default:` (colon in tag name)
    if value.endswith(':'):
        stripped = value.rstrip(':')
        near_matches = [inst.match(stripped) for inst in AVAILABLE_INSTRUCTIONS]
        for m in near_matches:
            if m:
                raise ValueError(
                    f"tag '{value}' looks like instruction '{stripped}' but has a trailing colon. "
                    f"YAML interprets `{value} key: val` as a tag named '{value}' (colon is part "
                    f"of the tag). Use `{stripped} key: val` (space, no colon after tag) instead."
                )
    return None
