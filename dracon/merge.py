# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

from typing import Optional, Any
import re
from pydantic import BaseModel
from enum import Enum
from dracon.utils import (
    dict_like,
    DictLike,
    ListLike,
    ftrace,
    deepcopy,
    list_like,
    clean_context_keys,
    values_equal,
    SoftPriorityDict,
)
from dracon.nodes import (
    MergeNode,
    DraconMappingNode,
    DraconSequenceNode,
    IncludeNode,
    node_source,
)
from dracon.diagnostics import CompositionError
from ruamel.yaml.nodes import Node
from dracon.keypath import KeyPath
from functools import lru_cache

import logging

logger = logging.getLogger(__name__)


def make_default_empty_mapping_node():
    return DraconMappingNode(
        tag='',
        value=[],
    )


_NON_CONSTRUCTIBLE_TAGS = frozenset({
    '', '!', 'tag:yaml.org,2002:map', 'tag:yaml.org,2002:seq',
    'tag:yaml.org,2002:str', 'tag:yaml.org,2002:int',
    'tag:yaml.org,2002:float', 'tag:yaml.org,2002:bool',
    'tag:yaml.org,2002:null', 'tag:yaml.org,2002:binary',
    'tag:yaml.org,2002:timestamp',
    '!include', '!include?', '!define', '!define?',
    '!set_default', '!require', '!assert', '!unset',
    '!fn', '!pipe', '!deferred', '!noconstruct',
})


def _has_constructible_tag(node):
    """True if a node's tag names a type/callable that must be realised before it
    can be used as a merge source. Default YAML tags, dracon builtins and empty
    tags don't count. Only applies to mapping/sequence sources - scalar merge
    sources (e.g. `!float 5` used with a keypath merge) are already handled
    correctly by the existing merge path."""
    if not isinstance(node, (DraconMappingNode, DraconSequenceNode)):
        return False
    tag = getattr(node, 'tag', None)
    if not tag or not isinstance(tag, str):
        return False
    if tag in _NON_CONSTRUCTIBLE_TAGS:
        return False
    # parametrised dracon builtins like !deferred::clear_ctx=foo also skip
    if tag.startswith('!deferred'):
        return False
    # interpolated tags ('!${...}' / '!$(...)') are still unresolved at this
    # stage - leave them to the tag resolution path
    if '${' in tag or '$(' in tag:
        return False
    return tag.startswith('!')


def _realize_tagged_merge_source(merge_node, loader):
    """Construct a tagged merge-source node so its *output* can be merged.

    When a merge source like `!Pool { seed_job: seed }` reaches process_merges
    it is still a tagged mapping whose children are the callable's arguments,
    not its result. If we merged it as-is, the callable's arguments would
    leak into the parent mapping and the tag would propagate, causing the
    parent to later be re-constructed as `!Pool` on the wrong shape (and any
    sibling keys of the parent would be fed in as extra unexpected kwargs).

    We fix this by running the construct pipeline on the source now, then
    converting the result back into a node that can be merged cleanly.
    Returns the realised node, or the original node if realisation fails or
    doesn't apply.
    """
    if loader is None:
        return merge_node
    if not _has_constructible_tag(merge_node):
        return merge_node
    from dracon.loader import dump_to_node
    try:
        result = loader.load_node(deepcopy(merge_node))
    except Exception as e:
        logger.debug(
            f"could not realise merge source with tag {merge_node.tag}: {e}. "
            f"falling back to naive merge."
        )
        return merge_node
    try:
        return dump_to_node(result)
    except Exception as e:
        logger.debug(
            f"could not dump realised merge source back to a node: {e}. "
            f"falling back to naive merge."
        )
        return merge_node


@ftrace(watch=[])
def process_merges(comp_res, loader=None):
    """
    Process all merge nodes in the composition result recursively until there are no more merges to process.
    Returns the modified composition result and whether any merges were performed.
    """
    from dracon.composer import walk_node
    from functools import partial
    any_merges = False

    while True:
        # find all merge nodes (re-discover each iteration so paths are fresh
        # after deletions that may renumber internal __merge_N_ keys)
        comp_res.find_special_nodes('merge', lambda n: isinstance(n, MergeNode))
        comp_res.sort_special_nodes('merge')

        if not comp_res.special_nodes['merge']:
            break

        any_merges = True

        # process one merge at a time then re-discover, matching the pattern
        # used by process_instructions -- this avoids stale paths when bare
        # duplicate merge keys (e.g. two `<<:`) share the same raw value and
        # deleting one causes renumbering in _recompute_map()
        merge_path = next(comp_res.pop_all_special('merge'))

        # get value path (remove mapping key)
        merge_path = merge_path.removed_mapping_key()
        merge_node = merge_path.get_obj(comp_res.root)
        parent_path = merge_path.copy().up()
        node_key = merge_path[-1]
        parent_node = parent_path.get_obj(comp_res.root)

        if not dict_like(parent_node):
            raise CompositionError(
                f"Parent of merge node must be a dictionary, got {type(parent_node).__name__}",
                context=node_source(merge_node),
            )

        if node_key not in parent_node:
            raise CompositionError(f"Merge key '{node_key}' not found in parent node", context=node_source(merge_node))
        key_node = parent_node.get_key(node_key)
        if not isinstance(key_node, MergeNode):
            raise CompositionError(
                f"Expected merge node, got {type(key_node).__name__} at key '{node_key}'",
                context=node_source(key_node),
            )

        try:
            merge_key = cached_merge_key(key_node.merge_key_raw)
        except Exception as e:
            raise CompositionError(
                f"Invalid merge key '{key_node.merge_key_raw}': {e}",
                context=node_source(merge_node),
            ) from e

        del parent_node[node_key]

        if merge_key.keypath:
            parent_path = parent_path + KeyPath(merge_key.keypath)

        new_parent = parent_path.get_obj(comp_res.root)
        # if the source has a constructible tag (e.g. !Pool, !Thing),
        # realise it *now* so its output -- not its arguments -- is what
        # gets merged into the parent.
        merge_node = _realize_tagged_merge_source(merge_node, loader)
        # propagate parent context into merge source so hard values
        # (!define) override soft values (!set_default) in the source.
        # existing-wins preserves the include's own !define values;
        # soft_keys logic in merged() still lets hard parent values beat soft ones.
        parent_ctx = getattr(new_parent, 'context', None)
        if parent_ctx and any(not k.startswith('__') for k in parent_ctx):
            merge_node = deepcopy(merge_node)
            from dracon.composer import walk_node as _walk
            _walk(merge_node, partial(add_to_context, parent_ctx, merge_key=cached_merge_key('<<{>~}[>~]')))
        new_parent = merged(new_parent, merge_node, merge_key)
        if not isinstance(new_parent, Node):
            raise CompositionError(f"Merge produced {type(new_parent).__name__} instead of a Node")

        comp_res.set_at(parent_path, new_parent)

        # record merge trace
        if comp_res.trace is not None:
            from dracon.composition_trace import TraceEntry, keypath_to_dotted
            priority_str = "new wins" if merge_key.dict_priority == MergePriority.NEW else "existing wins"
            _detail = f"{merge_key.raw}: {priority_str}"

            from dracon.loader import _get_node_source

            def _record_merge(node, path):
                if isinstance(node, (DraconMappingNode, DraconSequenceNode)):
                    return
                path_str = keypath_to_dotted(path)
                if path_str:
                    comp_res.trace.record(path_str, TraceEntry(
                        value=getattr(node, 'value', None),
                        source=_get_node_source(node),
                        via="merge",
                        detail=_detail,
                    ))

            walk_node(new_parent, _record_merge, start_path=parent_path)

        # propagate defined_vars to all nodes in new_parent if context propagation enabled
        if merge_key.context_propagation and comp_res.defined_vars:
            walk_node(new_parent, partial(add_to_context, comp_res.defined_vars))

        comp_res.make_map()

    return comp_res, any_merges


class MergeMode(Enum):
    # -> in the case of two dictionaries, append new keys
    # and will recursively merge subdict keys
    # when same keys are leaves and not dictionaries, see priority
    # when keys are lists, see list_mode
    # -> in the case of two lists, append new items
    APPEND = 'append'  # symbol: +

    # -> in the case of two dictionaries,
    # fully replace conflicting keys and append new keys
    # -> in the case of two lists, replace the whole list
    REPLACE = 'replace'  # symbol: ~


class MergePriority(Enum):
    NEW = 'new'  # symbol: <
    EXISTING = 'existing'  # symbol: >


class MergeKey(BaseModel):
    raw: str

    # dict mode default is >+
    dict_mode: MergeMode = MergeMode.APPEND
    dict_priority: MergePriority = MergePriority.EXISTING
    dict_depth: Optional[int] = None

    # list mode default is >~
    list_mode: MergeMode = MergeMode.REPLACE
    list_priority: MergePriority = MergePriority.EXISTING
    list_depth: Optional[int] = None

    # context propagation - whether to propagate new context up
    # only (<) is supported because modifying existing node's context doesn't make sense
    context_propagation: bool = False  # False (default) or True (with (<) option)

    keypath: Optional[str] = None

    @staticmethod
    def is_merge_key(key: str) -> bool:
        return key.startswith('<<')

    def get_mode_priority(
        self,
        mode_str: str,
        default_mode=MergeMode.APPEND,
        default_priority=MergePriority.EXISTING,
    ):
        # + means RECURSE or APPEND
        # ~ means REPLACE
        # > means EXISTING
        # < means NEW
        mode, priority = default_mode, default_priority
        assert '+' not in mode_str or '~' not in mode_str, (
            'Only one of + or ~ is allowed in dict_mode'
        )
        if '+' in mode_str:
            mode = MergeMode.APPEND
        if '~' in mode_str:
            mode = MergeMode.REPLACE
        assert '>' not in mode_str or '<' not in mode_str, (
            'Only one of > or < is allowed in dict_priority'
        )

        if '>' in mode_str:
            priority = MergePriority.EXISTING
        if '<' in mode_str:
            priority = MergePriority.NEW

        depth = None
        depth_str = re.search(r'(\d+)', mode_str)
        if depth_str:
            depth = int(depth_str.group(1))

        return mode, priority, depth

    def model_post_init(self, *args, **kwargs):
        # to find the dict_mode and list_mode, we need to parse the raw key
        # things inside {} concern the dict_mode and priority
        # things inside [] concern the list_mode and priority
        # things inside () concern the context propagation

        super().model_post_init(*args, **kwargs)

        # check that only zero or one [], {}, and () are present
        assert self.raw.count('{') <= 1, 'Only one {} is allowed in merge key'
        assert self.raw.count('[') <= 1, 'Only one [] is allowed in merge key'
        assert self.raw.count('(') <= 1, 'Only one () is allowed in merge key'
        # check that they close properly
        assert self.raw.count('{') == self.raw.count('}'), 'Mismatched {} in merge key'
        assert self.raw.count('[') == self.raw.count(']'), 'Mismatched [] in merge key'
        assert self.raw.count('(') == self.raw.count(')'), 'Mismatched () in merge key'

        # check if it has a keypath part (anything after @)
        default_dict_priority = MergePriority.EXISTING
        default_dict_mode = MergeMode.APPEND
        default_list_priority = MergePriority.EXISTING
        default_list_mode = MergeMode.REPLACE

        keypath_str = re.search(r'@(.+)', self.raw)
        if keypath_str:  # it's an @ keypath, aka an override
            self.keypath = keypath_str.group(1)
            # by default, we override with the new value
            default_dict_priority = MergePriority.NEW
            default_list_priority = MergePriority.NEW

        dict_str = re.search(r'{(.+)}', self.raw)
        if dict_str:
            dict_str = dict_str.group(1)
        else:
            dict_str = ''

        self.dict_mode, self.dict_priority, self.dict_depth = self.get_mode_priority(
            dict_str, default_mode=default_dict_mode, default_priority=default_dict_priority
        )

        list_str = re.search(r'\[(.+)\]', self.raw)
        if list_str:
            list_str = list_str.group(1)
        else:
            list_str = ''
        self.list_mode, self.list_priority, self.list_depth = self.get_mode_priority(
            list_str, default_mode=default_list_mode, default_priority=default_list_priority
        )

        # parse context propagation option
        context_str = re.search(r'\((.+)\)', self.raw)
        if context_str:
            context_str = context_str.group(1)
            if context_str == '<':
                self.context_propagation = True
            else:
                raise ValueError(f'Invalid context propagation option: {context_str}. Only < is allowed')


DEFAULT_ADD_TO_CONTEXT_MERGE_KEY = MergeKey(raw='<<{~<}[~<]')

# cache parsed MergeKey instances — same raw string always produces same result
_merge_key_cache: dict[str, MergeKey] = {}


def cached_merge_key(raw: str) -> MergeKey:
    mk = _merge_key_cache.get(raw)
    if mk is None:
        mk = MergeKey(raw=raw)
        _merge_key_cache[raw] = mk
    return mk


def merged(existing: Any, new: Any, k: MergeKey = DEFAULT_ADD_TO_CONTEXT_MERGE_KEY) -> DictLike:
    from dracon.deferred import DeferredNode

    # pre-compute flags to avoid repeated attribute access in inner loops
    _existing_wins = k.dict_priority == MergePriority.EXISTING
    _dict_append = k.dict_mode == MergeMode.APPEND
    _dict_depth = k.dict_depth
    _list_replace = k.list_mode == MergeMode.REPLACE
    _list_existing_wins = k.list_priority == MergePriority.EXISTING
    _list_depth = k.list_depth

    def merge_value(v1: Any, v2: Any, depth: int = 0) -> Any:
        if type(v1) is DeferredNode:
            return merge_value(v1.value, v2, depth)
        if type(v2) is DeferredNode:
            return merge_value(v1, v2.value, depth)

        # skip deep-merging nested objects that opt out (e.g. SymbolTable used as __scope__)
        if depth > 0 and (getattr(v1, '__dracon_no_merge__', False) or getattr(v2, '__dracon_no_merge__', False)):
            return v1 if _existing_wins else v2
        if type(v1) is type(v2) and hasattr(v1, 'merged_with') and hasattr(v2, 'merged_with'):
            return v1.merged_with(v2, depth + 1)
        elif dict_like(v1) and dict_like(v2):
            return merge_dicts(v1, v2, depth + 1)
        elif list_like(v1) and list_like(v2):
            return merge_lists(v1, v2, depth + 1)
        else:
            return v1 if _existing_wins else v2

    def merge_dicts(dict1: DictLike, dict2: DictLike, depth: int = 0) -> DictLike:
        pdict, other = (dict1, dict2) if _existing_wins else (dict2, dict1)

        if _dict_depth is not None and depth > _dict_depth:
            return pdict

        if hasattr(other, 'merged_with') and not hasattr(other, 'tag') and not hasattr(pdict, 'tag'):
            result = other.copy()
            result.update(pdict)
        else:
            result = pdict.copy()

        if hasattr(pdict, 'tag') and hasattr(other, 'tag'):
            if pdict.tag.startswith('!'):
                result.tag = pdict.tag
            elif other.tag.startswith('!'):
                result.tag = other.tag

        pdict_soft = getattr(pdict, '_soft_keys', None)
        other_soft = getattr(other, '_soft_keys', None)
        result_soft = getattr(result, '_soft_keys', None)

        for key, value in other.items():
            if key not in result:
                result[key] = value
                if other_soft and key in other_soft and result_soft is not None:
                    result_soft.add(key)
            elif pdict_soft and key in pdict_soft and not (other_soft and key in other_soft):
                result[key] = value
                if result_soft is not None:
                    result_soft.discard(key)
            elif _dict_append:
                result[key] = (
                    merge_value(result[key], value, depth + 1)
                    if _existing_wins
                    else merge_value(value, result[key], depth + 1)
                )
        return result

    def merge_lists(list1: ListLike, list2: ListLike, depth: int = 0) -> ListLike:
        if (_list_depth is not None and depth > _list_depth) or _list_replace:
            return list1 if _list_existing_wins else list2
        return list1 + list2 if _list_existing_wins else list2 + list1

    return merge_value(existing, new)


def _ensure_soft_dict(ctx):
    """Ensure context dict supports soft key tracking."""
    if ctx is None:
        return SoftPriorityDict()
    # SymbolTable: don't return as-is (would share the reference).
    # downgrade to SoftPriorityDict to keep node contexts independent.
    from dracon.symbol_table import SymbolTable
    if isinstance(ctx, SymbolTable):
        ctx._suspend_tracking = True
        try:
            spd = SoftPriorityDict(ctx)
        finally:
            ctx._suspend_tracking = False
        spd._soft_keys = set(ctx._soft_keys)
        return spd
    if hasattr(ctx, '_soft_keys'):
        return ctx
    # plain dict -> upgrade to SoftPriorityDict; other dict subclasses -> add _soft_keys attr
    if type(ctx) is dict:
        return SoftPriorityDict(ctx)
    # for specialized dict subclasses (e.g. TrackedContext), graft _soft_keys
    ctx._soft_keys = set()
    return ctx


def add_to_context(new_context, existing_item, merge_key=DEFAULT_ADD_TO_CONTEXT_MERGE_KEY, skip_clean=False):
    """
    Add context to the item context, if it exists.
    """
    if not skip_clean:
        new_context = clean_context_keys(new_context)

    ctx = getattr(existing_item, 'context', None)
    if ctx is not None:
        # fast path: skip_clean=True signals we're in the bulk context propagation loop.
        # for replace+existing with no soft keys on either side, just add missing keys.
        if (skip_clean
            and not merge_key.context_propagation
            and merge_key.dict_mode == MergeMode.REPLACE
            and merge_key.dict_priority == MergePriority.EXISTING
            and not getattr(ctx, '_soft_keys', None)
            and not getattr(new_context, '_soft_keys', None)):
            for k, v in new_context.items():
                if k not in ctx:
                    ctx[k] = v
        else:
            # SymbolTable: merge in-place to preserve type
            from dracon.symbol_table import SymbolTable
            if isinstance(ctx, SymbolTable):
                if merge_key.context_propagation:
                    mode_char = '+' if merge_key.dict_mode == MergeMode.APPEND else '~'
                    effective_key = cached_merge_key(f"{{{mode_char}<}}")
                else:
                    effective_key = merge_key
                _merge_into_symbol_table(ctx, new_context, effective_key)
            else:
                existing_item.context = _ensure_soft_dict(ctx)
                if merge_key.context_propagation:
                    mode_char = '+' if merge_key.dict_mode == MergeMode.APPEND else '~'
                    effective_key = cached_merge_key(f"{{{mode_char}<}}")
                else:
                    effective_key = merge_key
                existing_item.context = merged(existing_item.context, new_context, effective_key)
    else:
        existing_item.context = _ensure_soft_dict(new_context)

    if hasattr(existing_item, '_clear_ctx') and existing_item._clear_ctx:
        for k in existing_item._clear_ctx:
            if k in existing_item.context:
                del existing_item.context[k]


def _merge_into_symbol_table(table, new_context, merge_key):
    """Merge new_context into a SymbolTable in-place, respecting merge key semantics.

    Mirrors the soft key logic from merged()/merge_dicts():
    pdict is the priority dict (winner), other is the loser.
    If pdict has a soft key and other has a hard key, other's value wins.
    """
    existing_wins = merge_key.dict_priority == MergePriority.EXISTING
    new_soft = getattr(new_context, '_soft_keys', None)

    if existing_wins:
        # existing (table) is pdict, new_context is other
        for k, v in new_context.items():
            if k not in table:
                table[k] = v
                if new_soft and k in new_soft:
                    table._soft_keys.add(k)
            elif table.is_soft(k) and not (new_soft and k in new_soft):
                # pdict (table) has soft key, other (new) has hard key -> other wins
                table[k] = v
                table._soft_keys.discard(k)
    else:
        # new_context is pdict, table (existing) is other
        for k, v in new_context.items():
            if k not in table:
                table[k] = v
                if new_soft and k in new_soft:
                    table._soft_keys.add(k)
            else:
                # key exists in both
                is_new_soft = new_soft and k in new_soft
                is_existing_soft = table.is_soft(k)
                if is_new_soft and not is_existing_soft:
                    # pdict (new) has soft key, other (existing) has hard key -> other wins, skip
                    continue
                table[k] = v
                if is_new_soft:
                    table._soft_keys.add(k)
                else:
                    table._soft_keys.discard(k)


@ftrace(inputs=False, output=False, watch=[])
def reset_context(item, ignore_dracon_namespace=True):
    newctx = {}
    if hasattr(item, 'context'):
        for k, v in item.context.items():
            if ignore_dracon_namespace and k.startswith('__DRACON_'):
                newctx[k] = v
        item.context = newctx



def dict_diff(dict1, dict2):
    """
    Returns a dictionary with the differences between dict1 and dict2
    """
    diff = {}
    for key, value in dict1.items():
        if key not in dict2:
            diff[key] = value
        elif not values_equal(value, dict2[key]):
            if dict_like(value) and dict_like(dict2[key]):
                diff[key] = dict_diff(value, dict2[key])
            else:
                diff[key] = dict2[key]
    for key, value in dict2.items():
        if key not in dict1:
            diff[key] = value
    return diff


# ideal syntax:
# <<{>~}(attr1,attr2{+<}[+](subattr{~})): "value"
