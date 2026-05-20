# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
"""Discovery pre-pass must stay cheap regardless of argv-supplied values.

Bug class: ``Program._discover_yaml_args`` used to fold ``++name=value``
seeds straight into the loader context, so the discovery compose
expanded any ``!each`` / ``!if`` blocks against full user data. With a
cross-product over CLI-overridable lists, the compose ballooned to
seconds-to-minutes as override string length grew, producing a
perceived hang on the CLI's pre-parse step.

Discovery only needs to harvest ``!require`` / ``!set_default``
declarations -- it must not depend on the size of argv values.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from pydantic import BaseModel

from dracon import make_program


def _run_with_timeout(fn, *, timeout: float):
    box: dict = {}

    def _worker():
        try:
            box['result'] = fn()
        except BaseException as e:
            box['exc'] = e

    t = threading.Thread(target=_worker, daemon=True)
    start = time.monotonic()
    t.start()
    t.join(timeout=timeout)
    elapsed = time.monotonic() - start
    if t.is_alive():
        pytest.fail(f"timed out after {elapsed:.2f}s (limit {timeout}s)")
    return elapsed, box.get('exc')


YAML = """
!set_default subgroups: []
!set_default models: []
!define _pairs: ${[(m, sg) for m in models for sg in subgroups]}
result: !each(p) ${_pairs}:
  - "${p[0]['name']}__${p[1]['name']}"
"""


class Conf(BaseModel):
    result: Any = None
    subgroups: Any = []
    models: Any = []


def test_discovery_cost_independent_of_override_value_length(tmp_path):
    """parse_args time must not blow up with override string length.

    Pre-fix this was approximately linear with a steep slope (~0.2s
    per char) once a subcommand-shaped argv triggered the discovery
    pre-pass. Post-fix the slope is essentially flat because discovery
    no longer expands user data.
    """
    src = tmp_path / "p.yaml"
    src.write_text(YAML)

    def _runner(value_len):
        v = "a" * value_len
        prog = make_program(Conf, name="t")
        # ``--unknown-flag`` triggers _argv_needs_yaml_discovery so the
        # discovery pre-pass actually runs (exact same path the bug
        # report exercised via broodmon's subcommand flags).
        argv = [
            f"+{src}",
            f"++subgroups=[{{name: M, dataset_file: {v}}}]",
            f"++models=[{{name: M, path: {v}}}]",
            "--unknown-trigger-discovery",
        ]

        def _go():
            try:
                prog.parse_args(argv)
            except SystemExit:
                pass

        elapsed, exc = _run_with_timeout(_go, timeout=4.0)
        if exc is not None:
            raise exc
        return elapsed

    short = _runner(10)
    long = _runner(200)
    # generous bound; pre-fix this gap was tens of seconds
    assert long < short + 1.0, (
        f"discovery scales with override length: short={short:.2f}s, long={long:.2f}s"
    )
