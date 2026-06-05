# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

"""`!ref` / `!refs` -- the pull face of the locator atom.

`[type=X]` is an attribute condition (a node with a `type` field == "X"), not a
python-type check; bare-word predicates match by key or MRO. `!ref` with a
bracketed predicate must be block-style (YAML flow `{...}` chokes on `[...]`).
"""

import logging

import pytest
from pydantic import BaseModel

from dracon import loads
from dracon.interpolation import InterpolationError


class Widget(BaseModel):
    base: int
    computed: int = 0

    def model_post_init(self, _):
        self.computed = self.base * 2


def test_nearest_enclosing():
    cfg = loads("""
region: us-east-1
services:
  api:
    type: Service
    version: 2.3
    endpoints:
      health:
        on: !ref ^[type=Service].version
""")
    assert cfg["services"]["api"]["endpoints"]["health"]["on"] == 2.3


def test_sibling():
    cfg = loads("""
database:
  primary: { host: db1, port: 5432 }
  replica:
    host: db2
    port: !ref ^.primary.port
""")
    assert cfg["database"]["replica"]["port"] == 5432


def test_predicate_fanout():
    cfg = loads("""
services:
  api:    { tier: prod, port: 8080 }
  worker: { tier: dev,  port: 8081 }
  cron:   { tier: prod, port: 8082 }
scrape: !refs /services.*[tier=prod].port
""")
    assert cfg["scrape"] == [8080, 8082]


def test_predicate_fanout_bool_case_insensitive():
    # YAML `true` is a python bool; `=` is case-sensitive (str(True) == 'True'),
    # so booleans are matched with the case-insensitive `=~`.
    cfg = loads("""
services:
  api:    { enabled: true,  port: 8080 }
  worker: { enabled: false, port: 8081 }
scrape: !refs /services.*[enabled=~true].port
""")
    assert cfg["scrape"] == [8080]


def test_insertion_robust_pipeline():
    # reference upstream stages by identity, not list index
    cfg = loads("""
pipeline:
  - id: load
    out: raw
  - id: clean
    in: !ref ^.*[id=load].out
    out: cleaned
  - id: train
    in: !ref ^.*[id=clean].out
""")
    assert cfg["pipeline"][1]["in"] == "raw"
    assert cfg["pipeline"][2]["in"] == "cleaned"


def test_lazy_constructed_value_predicate():
    # [computed>0] reads a value set in model_post_init -> only matches at
    # post-construction (lazy) timing; b (computed==0) is excluded.
    cfg = loads(
        """
widgets:
  a: !Widget { base: 3 }
  b: !Widget { base: 0 }
selected: !refs /widgets.*[computed>0]
""",
        context={"Widget": Widget},
    )
    selected = cfg["selected"]
    assert [(w.base, w.computed) for w in selected] == [(3, 6)]


def test_lazy_predicate_does_not_force_unvisited_siblings(monkeypatch):
    # a predicate fan-out must not construct/resolve siblings it doesn't match
    inits = []
    orig = Widget.model_post_init

    def spy(self, ctx):
        inits.append(self.base)
        orig(self, ctx)

    monkeypatch.setattr(Widget, "model_post_init", spy)
    cfg = loads(
        """
widgets:
  a: !Widget { base: 3 }
  b: !Widget { base: 5 }
selected: !refs /widgets.*[computed>0]
""",
        context={"Widget": Widget},
    )
    _ = cfg["selected"]
    # each widget constructed exactly once (no re-construction during resolve)
    assert sorted(inits) == [3, 5]


def test_cross_file_include(tmp_path):
    base = tmp_path / "base.yaml"
    base.write_text("defaults:\n  timeout: 30\n  retries: 5\n")
    cfg = loads(f"""
<<: !include file:{base}
service:
  name: api
  timeout: !ref /defaults.timeout
""")
    # resolves over the merged tree (unlike `&` anchors, which can't reach include content)
    assert cfg["service"]["timeout"] == 30


def test_zero_match_errors():
    cfg = loads("a: 1\nb: !ref /nonexistent\n")
    with pytest.raises(InterpolationError):
        _ = cfg["b"]


def test_optional_zero_match_is_none():
    cfg = loads("a: 1\nb: !ref? /nonexistent\n")
    assert cfg["b"] is None


def test_refs_zero_match_is_empty_list():
    cfg = loads("a: 1\nb: !refs /nope.*\n")
    assert cfg["b"] == []


def test_ambiguous_single_returns_best_and_logs(caplog):
    with caplog.at_level(logging.WARNING, logger="dracon.locator"):
        cfg = loads("""
items:
  x: { kind: leaf, v: 1 }
  y: { kind: leaf, v: 2 }
pick: !ref /items.*[kind=leaf].v
""")
        picked = cfg["pick"]
    assert picked in (1, 2)
    assert any("ambiguous" in r.message for r in caplog.records)
