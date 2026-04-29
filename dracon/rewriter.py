# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

# compose-time tree rewriter shared by process_instructions / process_includes /
# process_merges / process_deferred. each pass plugs a discover predicate and an
# apply callback; the rewriter handles depth sort, re-discovery, fixpoint.
# trace integration via handler.trace_label / mutation_kind so provenance
# survives the consolidation.

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable, Iterator, Literal, Optional

from ruamel.yaml.nodes import Node

from dracon.composer import CompositionResult
from dracon.keypath import KeyPath


class MutationKind(Enum):
    DELETE = 'delete'
    REPLACE = 'replace'
    WRAP = 'wrap'
    MERGE = 'merge'


class RewriteResult(Enum):
    MUTATED = 'mutated'  # tree changed, re-discover before next match
    DEFERRED = 'deferred'  # leave for caller to retry later
    NO_CHANGE = 'no_change'  # mark visited, do not re-discover


DiscoverFn = Callable[[Node, KeyPath], bool]
ApplyFn = Callable[[CompositionResult, KeyPath, Node], RewriteResult]
SkipFn = Callable[[CompositionResult], Iterable[KeyPath]]


@dataclass(frozen=True, slots=True)
class RewriteHandler:
    name: str
    discover: DiscoverFn
    apply: ApplyFn
    trace_label: str
    mutation_kind: MutationKind
    restart_other_passes: bool = False
    skip_under: Optional[SkipFn] = None  # paths whose subtrees the rewriter must ignore


@dataclass
class RewriteOutcome:
    mutated: bool = False
    deferred: list[tuple[KeyPath, Node]] = field(default_factory=list)
    iterations: int = 0


class NodeRewriter:
    """walk a CompositionResult, find matches via handler.discover, dispatch to
    handler.apply, re-discover after each MUTATED result, repeat until no more
    matches. one-mutation-at-a-time keeps paths fresh in the face of sibling
    deletions / renumbering."""

    def __init__(
        self,
        comp_res: CompositionResult,
        handler: RewriteHandler,
        *,
        order: Literal['longest_first', 'shortest_first', 'dfs'] = 'longest_first',
        max_passes: int = 10000,
    ):
        self.comp = comp_res
        self.handler = handler
        self.order = order
        self.max_passes = max_passes

    # --- discovery ---------------------------------------------------------

    def _skip_paths(self) -> tuple[KeyPath, ...]:
        if self.handler.skip_under is None:
            return ()
        return tuple(self.handler.skip_under(self.comp))

    def _is_under(self, path: KeyPath, prefixes: tuple[KeyPath, ...]) -> bool:
        if not prefixes:
            return False
        from dracon.instructions import path_is_under_any
        return path_is_under_any(path, prefixes)

    def _iter_candidates(self) -> Iterator[tuple[KeyPath, Node]]:
        assert self.comp.node_map is not None
        skip = self._skip_paths()
        for path, node in self.comp.node_map.items():
            if self._is_under(path, skip):
                continue
            if self.handler.discover(node, path):
                yield path, node

    def _ordered_candidates(self) -> list[tuple[KeyPath, Node]]:
        candidates = list(self._iter_candidates())
        if self.order == 'longest_first':
            candidates.sort(key=lambda p: len(p[0]), reverse=True)
        elif self.order == 'shortest_first':
            candidates.sort(key=lambda p: len(p[0]))
        # 'dfs' keeps node_map iteration order (DFS by construction)
        return candidates

    # --- main loop ---------------------------------------------------------

    def run(self) -> RewriteOutcome:
        outcome = RewriteOutcome()
        # skipped tracks (path-key, id) pairs that returned DEFERRED / NO_CHANGE.
        # we re-clear it after every MUTATED because mutation can recycle ids
        # (freed nodes' ids get reused for newly inserted nodes) and may also
        # unblock previously deferred work.
        skipped: set[tuple] = set()
        deferred_pending: dict[tuple, tuple[KeyPath, Node]] = {}

        for _ in range(self.max_passes):
            outcome.iterations += 1
            self.comp.make_map()
            candidates = self._ordered_candidates()
            candidates = [
                (p, n) for p, n in candidates if (str(p), id(n)) not in skipped
            ]
            if not candidates:
                break

            path, node = candidates[0]
            result = self.handler.apply(self.comp, path.copy(), node)
            if result is RewriteResult.MUTATED:
                outcome.mutated = True
                skipped.clear()
                deferred_pending.clear()
            elif result is RewriteResult.DEFERRED:
                key = (str(path), id(node))
                deferred_pending[key] = (path.copy(), node)
                skipped.add(key)
            else:  # NO_CHANGE
                skipped.add((str(path), id(node)))
        else:
            raise RuntimeError(
                f"NodeRewriter[{self.handler.name}] exceeded max_passes={self.max_passes}"
            )

        outcome.deferred = list(deferred_pending.values())
        return outcome
