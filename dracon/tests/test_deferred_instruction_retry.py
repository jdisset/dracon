# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

import pytest

from dracon.diagnostics import CompositionError
from dracon.loader import DraconLoader


VOCAB_AND_LAZY_DEFINE = """
<<(<): !include pkg:dracon:tests/test_vocab_define_propagation_vocab.yaml
!define D: !greet
  name: world
"""


def test_deferred_if_false_branch_is_opaque_until_retry():
    cfg = DraconLoader(enable_interpolation=True).loads(
        VOCAB_AND_LAZY_DEFINE
        + """
!if ${len(D) < 0}:
  !require missing: "must be skipped"
  !assert ${False}: "must be skipped"
  bad: !include file:/tmp/_dracon_missing_false_branch.yaml
fallback: ok
"""
    )
    assert cfg["fallback"] == "ok"
    assert "bad" not in cfg


def test_deferred_if_true_branch_contracts_run_after_retry():
    with pytest.raises(CompositionError, match="assertion failed: runs after retry"):
        DraconLoader(enable_interpolation=True).loads(
            VOCAB_AND_LAZY_DEFINE
            + """
!if ${len(D) > 0}:
  !assert ${False}: "runs after retry"
  enabled: true
"""
        )


def test_deferred_each_body_instructions_run_after_retry():
    cfg = DraconLoader(enable_interpolation=True).loads(
        VOCAB_AND_LAZY_DEFINE
        + """
!each(x) ${[D]}:
  !define y: ${x}
  result_${len(x)}: ${y}
"""
    )
    cfg.resolve_all_lazy()
    assert cfg["result_13"] == "Hello, world!"
