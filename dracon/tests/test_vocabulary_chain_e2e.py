# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""End-to-end tests inspired by real layered-vocabulary configs.

Three angles the rest of the suite under-covers:

1. Three-level vocabulary chain (file A propagates to B propagates to C),
   exercising scope hopping, hard-vs-soft binding precedence across include
   boundaries, and tag resolution for symbols introduced 2+ levels up.

2. ``!fn`` templates whose bodies contain composition-time ``!if`` / ``!each``
   instructions that fire on each call's deep-copied node.

3. Template-as-merge-source: ``<<: !MyTemplate {kwargs}`` merging a template's
   expansion into a parent mapping, and combining with merge strategy operators.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

import dracon
from dracon import DraconLoader


def _write(tmp: Path, name: str, body: str) -> Path:
    path = tmp / name
    path.write_text(textwrap.dedent(body).lstrip())
    return path


# ── 1. Three-level vocabulary chain ──────────────────────────────────────────


class TestThreeLevelVocabularyChain:
    """File C propagates B propagates A. Symbols hop down two boundaries."""

    def test_leaf_uses_template_defined_two_levels_up(self, tmp_path: Path):
        # level A: defines a base !fn template
        a = _write(tmp_path, "a.yaml", """
            !define Endpoint: !fn
              !require name: "service name"
              !set_default port: 8080
              url: "https://${name}.internal:${port}"
        """)
        # level B: includes A and defines a !fn that *uses* A's template via tag
        b = _write(tmp_path, "b.yaml", f"""
            <<(<): !include file:{a}
            !define Cluster: !fn
              !require region: "deployment region"
              !set_default svc_name: "api"
              region: ${{region}}
              endpoint: !Endpoint
                name: ${{svc_name}}
                port: 443
        """)
        # level C: includes B and invokes the B-level template via tag
        c = _write(tmp_path, "c.yaml", f"""
            <<(<): !include file:{b}
            production: !Cluster
              region: us-east-1
              svc_name: payments
        """)

        cfg = dracon.load(str(c))
        assert cfg["production"]["region"] == "us-east-1"
        assert cfg["production"]["endpoint"]["url"] == "https://payments.internal:443"

    def test_leaf_define_overrides_set_default_two_levels_up(self, tmp_path: Path):
        """Hard binding at the leaf beats !set_default deeper in the chain."""
        a = _write(tmp_path, "a.yaml", """
            !set_default tier: bronze
            !set_default replicas: 1
        """)
        b = _write(tmp_path, "b.yaml", f"""
            <<(<): !include file:{a}
            !set_default tier: silver
        """)
        c = _write(tmp_path, "c.yaml", f"""
            <<(<): !include file:{b}
            !define tier: gold
            tier_value: ${{tier}}
            replicas_value: ${{replicas}}
        """)
        cfg = dracon.load(str(c))
        assert cfg["tier_value"] == "gold"          # leaf !define wins
        assert cfg["replicas_value"] == 1            # untouched, falls through

    def test_scope_visible_from_all_levels(self, tmp_path: Path):
        """__scope__ at the leaf sees A, B, C symbols together."""
        a = _write(tmp_path, "a.yaml", """!define alpha: 1\n""")
        b = _write(tmp_path, "b.yaml", f"""
            <<(<): !include file:{a}
            !define beta: 2
        """)
        c = _write(tmp_path, "c.yaml", f"""
            <<(<): !include file:{b}
            !define gamma: 3
            has_alpha: ${{__scope__.has('alpha')}}
            has_beta: ${{__scope__.has('beta')}}
            has_gamma: ${{__scope__.has('gamma')}}
            sum: ${{alpha + beta + gamma}}
        """)
        cfg = dracon.load(str(c))
        assert cfg["has_alpha"] is True
        assert cfg["has_beta"] is True
        assert cfg["has_gamma"] is True
        assert cfg["sum"] == 6

    def test_a_level_type_resolves_through_b_template_at_c(self, tmp_path: Path):
        """A registers a Python type via context_types; B builds it inside its
        !fn body; C invokes B's !fn — A's type resolves at C's construction."""
        from pydantic import BaseModel

        class Service(BaseModel):
            name: str
            port: int = 80

        a = _write(tmp_path, "a.yaml", """
            !define _placeholder: 0
        """)
        b = _write(tmp_path, "b.yaml", f"""
            <<(<): !include file:{a}
            !define MakeService: !fn
              !require sname: "service name"
              !set_default sport: 8080
              !fn : !Service
                name: ${{sname}}
                port: ${{sport}}
        """)
        c = _write(tmp_path, "c.yaml", f"""
            <<(<): !include file:{b}
            svc: ${{MakeService(sname='auth', sport=9000)}}
        """)
        loader = DraconLoader(context={"Service": Service})
        cfg = loader.load(str(c))
        assert isinstance(cfg["svc"], Service)
        assert cfg["svc"].name == "auth"
        assert cfg["svc"].port == 9000


# ── 2. !fn templates with composition-time instructions in body ─────────────


class TestFnTemplateWithCompositionInstructions:
    """!if / !each inside a !fn body fire on each invocation's deep-copied node."""

    def _loads(self, yaml: str, **ctx):
        return DraconLoader(context=ctx).loads(textwrap.dedent(yaml).lstrip())

    def test_if_inside_fn_gates_on_per_call_kwarg(self):
        """Each invocation evaluates !if independently against its own kwargs."""
        cfg = self._loads("""
            !define MaybeMonitor: !fn
              !require name: "service"
              !set_default monitored: false
              endpoint: "https://${name}.example.com"
              !if ${monitored}:
                metrics_url: "https://${name}.example.com/metrics"

            plain: !MaybeMonitor { name: api }
            watched: !MaybeMonitor { name: db, monitored: true }
        """)
        assert "metrics_url" not in cfg["plain"]
        assert cfg["watched"]["metrics_url"] == "https://db.example.com/metrics"

    def test_if_branches_with_then_inside_fn(self):
        """The then:/else: explicit-branch form works inside a !fn body."""
        cfg = self._loads("""
            !define Tier: !fn
              !require env: "environment"
              !if ${env == 'prod'}:
                then:
                  retries: 5
                  ssl: true
                else:
                  retries: 1
                  ssl: false

            prod: !Tier { env: prod }
            dev:  !Tier { env: dev }
        """)
        assert cfg["prod"]["retries"] == 5 and cfg["prod"]["ssl"] is True
        assert cfg["dev"]["retries"] == 1 and cfg["dev"]["ssl"] is False

    def test_each_inside_fn_iterates_per_call_kwarg(self):
        """!each inside a !fn body fans out per-call lists."""
        cfg = self._loads("""
            !define Cluster: !fn
              !require region: "region"
              !require nodes: "list of node names"
              region: ${region}
              hosts:
                !each(n) ${nodes}:
                  - ${n}.${region}.internal

            west: !Cluster
              region: us-west
              nodes: [a, b, c]
        """)
        assert cfg["west"]["region"] == "us-west"
        assert cfg["west"]["hosts"] == [
            "a.us-west.internal",
            "b.us-west.internal",
            "c.us-west.internal",
        ]

    def test_consecutive_calls_do_not_leak_kwargs(self):
        """Deep-copy semantics: call N+1's kwargs must not overwrite call N's."""
        cfg = self._loads("""
            !define Box: !fn
              !require name: "box name"
              !set_default count: 1
              name: ${name}
              count: ${count}

            a: !Box { name: alpha, count: 10 }
            b: !Box { name: beta }
            c: !Box { name: gamma, count: 99 }
        """)
        # element access triggers lazy resolution; compare via plain dicts
        assert dict(cfg["a"]) == {"name": "alpha", "count": 10}
        assert dict(cfg["b"]) == {"name": "beta",  "count": 1}
        assert dict(cfg["c"]) == {"name": "gamma", "count": 99}

    def test_nested_if_inside_each_inside_fn(self):
        """Composition-time directives compose inside a template body."""
        cfg = self._loads("""
            !define Sweep: !fn
              !require sizes: "list of sizes"
              !set_default include_small: true
              configs:
                !each(s) ${sizes}:
                  !if ${s >= 64 or include_small}:
                    - size: ${s}

            full: !Sweep { sizes: [16, 32, 64, 128] }
            big_only: !Sweep { sizes: [16, 32, 64, 128], include_small: false }
        """)
        assert [c["size"] for c in cfg["full"]["configs"]] == [16, 32, 64, 128]
        assert [c["size"] for c in cfg["big_only"]["configs"]] == [64, 128]


# ── 3. Template-as-merge-source ──────────────────────────────────────────────


class TestTemplateAsMergeSource:
    """``<<: !MyTemplate {kwargs}`` merges a template's expansion into a parent."""

    def _loads(self, yaml: str, **ctx):
        return DraconLoader(context=ctx).loads(textwrap.dedent(yaml).lstrip())

    def test_template_expansion_merges_into_parent_mapping(self):
        cfg = self._loads("""
            !define Defaults: !fn
              !set_default port: 8080
              !set_default host: "localhost"
              port: ${port}
              host: ${host}
              protocol: http

            service:
              <<: !Defaults { port: 9000 }
              name: my-api
        """)
        # template-supplied keys merged in
        assert cfg["service"]["port"] == 9000
        assert cfg["service"]["host"] == "localhost"
        assert cfg["service"]["protocol"] == "http"
        # parent's own keys preserved
        assert cfg["service"]["name"] == "my-api"

    def test_parent_keys_override_template_keys_under_default_merge(self):
        """Default merge: existing keys in parent win over the new merged-in keys."""
        cfg = self._loads("""
            !define Base: !fn
              !set_default level: info
              level: ${level}
              format: text

            config:
              <<: !Base { level: debug }
              level: error      # parent's value should win under default merge
        """)
        # default merge precedence: existing keys win
        assert cfg["config"]["level"] == "error"
        assert cfg["config"]["format"] == "text"

    def test_template_in_deep_merge_strategy(self):
        """``<<:`` (default existing-wins) deep-merges template fill-ins."""
        cfg = self._loads("""
            !define Defaults: !fn
              !set_default db_host: "localhost"
              database:
                host: ${db_host}
                port: 5432
                pool: { min: 2, max: 10 }

            config:
              <<: !Defaults { db_host: prod-db }
              database:
                pool:
                  max: 50            # parent's leaf override wins under default merge
        """)
        db = cfg["config"]["database"]
        assert db["host"] == "prod-db"   # template provided, parent didn't override
        assert db["port"] == 5432
        assert db["pool"]["min"] == 2     # template's value flows through
        assert db["pool"]["max"] == 50    # parent's override wins (existing wins)

    def test_template_in_new_wins_merge_strategy(self):
        """``<<{<+}:`` recursive new-wins: template's leaves override parent's."""
        cfg = self._loads("""
            !define Override: !fn
              !set_default level: warn
              logging:
                level: ${level}
                format: json

            config:
              logging:
                level: debug          # parent's value (existing)
                handler: file
              <<{<+}: !Override { level: error }    # source wins
        """)
        log = cfg["config"]["logging"]
        assert log["level"] == "error"   # source (template) wins under <
        assert log["format"] == "json"   # source-only key flows in
        assert log["handler"] == "file"  # parent-only key preserved

    def test_template_with_inner_if_as_merge_source(self):
        """Template body's !if fires before the merge runs."""
        cfg = self._loads("""
            !define Profile: !fn
              !require env: "env"
              base_setting: 1
              !if ${env == 'prod'}:
                ssl: true
                replicas: 5
              !if ${env == 'dev'}:
                debug: true

            prod_cfg:
              <<: !Profile { env: prod }
              owner: alice

            dev_cfg:
              <<: !Profile { env: dev }
              owner: bob
        """)
        assert cfg["prod_cfg"]["ssl"] is True
        assert cfg["prod_cfg"]["replicas"] == 5
        assert "debug" not in cfg["prod_cfg"]
        assert cfg["prod_cfg"]["owner"] == "alice"

        assert cfg["dev_cfg"]["debug"] is True
        assert "ssl" not in cfg["dev_cfg"]
        assert cfg["dev_cfg"]["owner"] == "bob"
