# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
"""`__extras__`: kwargs not bound to a declared `!require` / `!set_default`
are collected into a dict bound under that name in the template body's scope.
Mirrors Python's `**kwargs`."""
from dracon import loads, resolve_all_lazy


class TestExtrasBasic:
    def test_extras_empty_when_only_declared_passed(self):
        yaml = """
        !define f: !fn
          !require x: "..."
          got: ${__extras__}
        result: !f { x: 1 }
        """
        cfg = loads(yaml); resolve_all_lazy(cfg)
        assert cfg["result"]["got"] == {}

    def test_extras_collects_undeclared(self):
        yaml = """
        !define f: !fn
          !require x: "..."
          got: ${__extras__}
        result: !f { x: 1, a: 10, b: 20 }
        """
        cfg = loads(yaml); resolve_all_lazy(cfg)
        assert cfg["result"]["got"] == {"a": 10, "b": 20}

    def test_extras_excludes_set_default(self):
        yaml = """
        !define f: !fn
          !require x: "..."
          !set_default y: 99
          got: ${__extras__}
        result: !f { x: 1, y: 2, z: 3 }
        """
        cfg = loads(yaml); resolve_all_lazy(cfg)
        assert cfg["result"]["got"] == {"z": 3}

    def test_extras_excludes_set_default_when_not_passed(self):
        yaml = """
        !define f: !fn
          !require x: "..."
          !set_default y: 99
          got: ${__extras__}
        result: !f { x: 1, z: 3 }
        """
        cfg = loads(yaml); resolve_all_lazy(cfg)
        assert cfg["result"]["got"] == {"z": 3}


class TestExtrasForwarding:
    def test_extras_spread_into_merge(self):
        yaml = """
        !define wrap: !fn
          !require name: "..."
          result:
            name: ${name}
            <<{<+}: ${__extras__}
        out: !wrap { name: foo, color: red, size: big }
        """
        cfg = loads(yaml); resolve_all_lazy(cfg)
        assert cfg["out"]["result"] == {"name": "foo", "color": "red", "size": "big"}

    def test_extras_forwarded_to_inner_template(self):
        yaml = """
        !define inner: !fn
          !require name: "..."
          built:
            name: ${name}
            rest: ${__extras__}

        !define outer: !fn
          !require name: "..."
          out: !inner
            name: ${name}
            <<{<+}: ${__extras__}

        result: !outer { name: x, a: 1, b: 2 }
        """
        cfg = loads(yaml); resolve_all_lazy(cfg)
        assert cfg["result"]["out"]["built"] == {"name": "x", "rest": {"a": 1, "b": 2}}


class TestExtrasScoping:
    def test_inner_extras_distinct_from_outer(self):
        yaml = """
        !define inner: !fn
          !require a: "..."
          here: ${__extras__}

        !define outer: !fn
          !require x: "..."
          outer_extras: ${__extras__}
          inner_call: !inner { a: 1, foo: 99 }

        result: !outer { x: 1, bar: 42 }
        """
        cfg = loads(yaml); resolve_all_lazy(cfg)
        assert cfg["result"]["outer_extras"] == {"bar": 42}
        assert cfg["result"]["inner_call"]["here"] == {"foo": 99}

    def test_extras_not_leaking_to_outer_scope(self):
        yaml = """
        !define f: !fn
          !require x: "..."
          here: ${__extras__}
        inside: !f { x: 1, extra: 7 }
        outside_has_extras: ${'__extras__' in __scope__}
        """
        cfg = loads(yaml); resolve_all_lazy(cfg)
        assert cfg["inside"]["here"] == {"extra": 7}
        assert cfg["outside_has_extras"] is False


