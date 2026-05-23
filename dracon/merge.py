# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

from typing import Optional, Any, Callable
import re
from pydantic import BaseModel, ConfigDict, Field
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


def _realize_interpolable_merge_source(merge_node, loader):
    """Evaluate a `${...}` merge source so `merged()` sees the concrete
    value. A scalar InterpolableNode would otherwise fall through to the
    scalar-replacement branch and wipe the parent mapping."""
    from dracon.interpolation import InterpolableNode
    if not isinstance(merge_node, InterpolableNode) or not merge_node.init_outermost_interpolations:
        return merge_node
    try:
        value = merge_node.evaluate()
    except Exception as e:
        raise CompositionError(
            f"merge source {merge_node.value!r} could not be evaluated at "
            f"compose time: {type(e).__name__}: {e}\n"
            "Merge keys want compose-time values: use `!include`, an "
            "inline mapping, an anchor, or a `!define`-bound value.",
            context=node_source(merge_node),
        ) from e
    from dracon.loader import dump_to_node
    realised = dump_to_node(value)
    realised.context = getattr(merge_node, 'context', None) or getattr(realised, 'context', None)
    return realised


def _apply_one_merge(comp_res, merge_key_path: KeyPath, loader):
    """apply a single merge: delete the merge-key, splice the value into parent
    via merged(), record trace, propagate defined_vars."""
    from dracon.composer import walk_node
    from functools import partial

    merge_path = merge_key_path.removed_mapping_key()
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
        raise CompositionError(
            f"Merge key '{node_key}' not found in parent node",
            context=node_source(merge_node),
        )
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
    # realise tagged merge source (!Pool, !Thing) *now* so its output is what gets merged
    merge_node = _realize_tagged_merge_source(merge_node, loader)
    # realise lazy scalar merge source (`<<: ${dict}`) the same way
    merge_node = _realize_interpolable_merge_source(merge_node, loader)
    # propagate parent context into merge source so !define beats !set_default,
    # existing-wins preserves the include's own !define values
    parent_ctx = getattr(new_parent, 'context', None)
    if parent_ctx and any(not k.startswith('__') for k in parent_ctx):
        # fast tree copy avoids the per-node copy.deepcopy dispatch overhead
        from dracon.composer import fast_copy_node_tree, walk_node as _walk
        merge_node = fast_copy_node_tree(merge_node)
        _walk(merge_node, partial(add_to_context, parent_ctx, merge_key=cached_merge_key('<<{>~}[>~]')))
    new_parent = merged(new_parent, merge_node, merge_key)
    if not isinstance(new_parent, Node):
        raise CompositionError(
            f"Merge produced {type(new_parent).__name__} instead of a Node"
        )

    comp_res.set_at(parent_path, new_parent)

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

    if merge_key.context_propagation and comp_res.defined_vars:
        walk_node(new_parent, partial(add_to_context, comp_res.defined_vars))


@ftrace(watch=[])
def process_merges(comp_res, loader=None, skip_paths=()):
    """Apply all merge nodes (`<<:` keys) in the tree until quiescent.

    Returns (comp_res, mutated_bool). One merge is applied at a time then the
    rewriter re-discovers -- this keeps paths fresh when bare duplicate merge
    keys (e.g. two `<<:`) share the same raw value and deleting one renumbers
    the internal `__merge_N_` keys.
    """
    from dracon.rewriter import (
        NodeRewriter,
        RewriteHandler,
        RewriteResult,
        MutationKind,
    )

    skip_tuple = tuple(skip_paths) if skip_paths else ()

    def discover(node, path):
        return isinstance(node, MergeNode)

    def apply(comp, path, node):
        _apply_one_merge(comp, path, loader)
        return RewriteResult.MUTATED

    handler = RewriteHandler(
        name='process_merges',
        discover=discover,
        apply=apply,
        trace_label='merge',
        mutation_kind=MutationKind.MERGE,
        restart_other_passes=False,
        skip_under=(lambda c: skip_tuple) if skip_tuple else None,
    )
    outcome = NodeRewriter(comp_res, handler, order='longest_first').run()
    if outcome.mutated:
        comp_res.make_map()
    return comp_res, outcome.mutated


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
    model_config = ConfigDict(arbitrary_types_allowed=True)

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

    # normalises string keys before equality; None on a key falls back to name-equality
    key_normalize: Optional[Callable[[str], Optional[str]]] = Field(default=None, exclude=True)

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

# cache parsed MergeKey instances -- same raw string always produces same result
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
    _normalize = k.key_normalize

    def _norm(key):
        if _normalize is None or not isinstance(key, str):
            return None
        return _normalize(key)

    def merge_value(v1: Any, v2: Any, depth: int = 0) -> Any:
        if type(v1) is DeferredNode:
            return merge_value(v1.value, v2, depth)
        if type(v2) is DeferredNode:
            return merge_value(v1, v2.value, depth)

        # skip deep-merging nested objects that opt out (e.g. SymbolTable used as __scope__)
        if depth > 0 and (getattr(v1, '__dracon_no_merge__', False) or getattr(v2, '__dracon_no_merge__', False)):
            return v1 if _existing_wins else v2

        # peer cascade merge: same-strategy cascades crossing a merge boundary
        # union their bodies (symmetric or asymmetric stack case)
        from dracon.cascade import try_peer_cascade_merge
        cascade_res = try_peer_cascade_merge(v1, v2, k)
        if cascade_res is not None:
            return cascade_res

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

        # bypass SymbolTable source lookups (each miss fires importlib)
        result_entries = getattr(result, '_entries', None)
        _result_contains = result_entries.__contains__ if result_entries is not None else result.__contains__

        # normalized -> existing key index; built only when hook is active
        norm_index: Optional[dict] = None
        if _normalize is not None:
            norm_index = {}
            for ek in result.keys():
                en = _norm(ek)
                if en is not None:
                    norm_index[en] = ek

        for key, value in other.items():
            new_norm = _norm(key) if norm_index is not None else None
            if new_norm is not None and new_norm in norm_index:
                target = norm_index[new_norm]
            elif _result_contains(key):
                target = key
            else:
                target = None

            if target is None:
                result[key] = value
                if norm_index is not None and new_norm is not None:
                    norm_index[new_norm] = key
                if other_soft and key in other_soft and result_soft is not None:
                    result_soft.add(key)
            elif pdict_soft and target in pdict_soft and not (other_soft and key in other_soft):
                result[target] = value
                if result_soft is not None:
                    result_soft.discard(target)
            elif _dict_append:
                result[target] = (
                    merge_value(result[target], value, depth + 1)
                    if _existing_wins
                    else merge_value(value, result[target], depth + 1)
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
    # SymbolTable.copy() is an entries-dict copy -- no per-symbol materialization
    from dracon.symbol_table import SymbolTable
    if isinstance(ctx, SymbolTable):
        return ctx.copy()
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
        # short-circuit: same SymbolTable already attached -- nothing to merge in
        if ctx is new_context:
            if hasattr(existing_item, '_clear_ctx') and existing_item._clear_ctx:
                for k in existing_item._clear_ctx:
                    if k in ctx:
                        del ctx[k]
            return

        # bulk-propagation fast path: replace+existing with no soft keys = just add missing
        from dracon.symbol_table import SymbolTable
        if (skip_clean
            and not merge_key.context_propagation
            and merge_key.dict_mode == MergeMode.REPLACE
            and merge_key.dict_priority == MergePriority.EXISTING
            and not getattr(ctx, '_soft_keys', None)
            and not getattr(new_context, '_soft_keys', None)):
            if isinstance(ctx, SymbolTable):
                if isinstance(new_context, SymbolTable) and ctx.is_synced_with(new_context):
                    return
                ctx_entries = ctx._entries
                if isinstance(new_context, SymbolTable):
                    for k, entry in new_context._entries.items():
                        if k not in ctx_entries:
                            ctx.define(entry)
                else:
                    for k, v in new_context.items():
                        if k not in ctx_entries:
                            ctx[k] = v
            else:
                for k, v in new_context.items():
                    if k not in ctx:
                        ctx[k] = v
        else:
            if merge_key.context_propagation:
                mode_char = '+' if merge_key.dict_mode == MergeMode.APPEND else '~'
                effective_key = cached_merge_key(f"{{{mode_char}<}}")
            else:
                effective_key = merge_key
            if isinstance(ctx, SymbolTable):
                _merge_into_symbol_table(ctx, new_context, effective_key)
            else:
                existing_item.context = _ensure_soft_dict(ctx)
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

    When new_context is also a SymbolTable, entries are preserved whole
    (source, canonical flag, docs). Plain-dict merges route through
    __setitem__ and produce non-canonical entries.
    """
    from dracon.symbol_table import SymbolTable

    existing_wins = merge_key.dict_priority == MergePriority.EXISTING
    new_is_table = isinstance(new_context, SymbolTable)

    # synced clone of new_context (or superset) is a no-op for existing-wins
    if existing_wins and new_is_table and table.is_synced_with(new_context):
        return

    new_soft = getattr(new_context, '_soft_keys', None)
    table_entries = table._entries
    table_soft = table._soft_keys
    table_parent = table._parent

    # cheap membership check that skips SymbolTable source lookups
    def _local_in_table(k):
        if k in table_entries:
            return True
        p = table_parent
        while p is not None:
            if k in p._entries:
                return True
            p = p._parent
        return False

    # iterate raw entries when possible to skip the materializing items() view
    if new_is_table:
        items = new_context._entries.items()
        def _write(k, payload): table.define(payload)
    else:
        items = new_context.items()
        def _write(k, payload): table[k] = payload

    for k, payload in items:
        is_new_soft = bool(new_soft and k in new_soft)
        if not _local_in_table(k):
            _write(k, payload)
            if is_new_soft:
                table_soft.add(k)
            continue
        is_existing_soft = k in table_soft
        if existing_wins:
            if is_existing_soft and not is_new_soft:
                _write(k, payload)
                table_soft.discard(k)
        else:
            if is_new_soft and not is_existing_soft:
                continue
            _write(k, payload)
            if is_new_soft:
                table_soft.add(k)
            else:
                table_soft.discard(k)


@ftrace(inputs=False, output=False, watch=[])
def reset_context(item, ignore_dracon_namespace=True):
    newctx = {}
    if hasattr(item, 'context'):
        for k, v in item.context.items():
            if ignore_dracon_namespace and k.startswith('__DRACON_'):
                newctx[k] = v
        item.context = newctx



