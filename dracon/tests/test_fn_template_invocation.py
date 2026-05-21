# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
"""Symmetry of `!fn` template tag invocation: scalar positional, kwarg mapping,
and call-site `@/path` references.

Two bug clusters are covered here:

1. Tag-form scalar invocation of a template silently dropped the positional
   instead of binding it to the first `!require` parameter. Plain Python
   callables and `!fn:target` partials honoured the documented "scalar becomes
   one positional arg" rule but templates/pipes did not.

2. `${@/path}` passed as a kwarg at the call site evaluated against the kwargs
   mapping itself rather than the caller's tree root. The lazy's captured
   `root_obj` (caller root) was being overwritten with the local kwargs dict.
"""
import pytest
from dracon import loads, resolve_all_lazy


# ────────────────────────────────────────────────────────────────────────────
# scalar positional bound to first !require
# ────────────────────────────────────────────────────────────────────────────


class TestScalarPositional:
    def test_scalar_binds_to_first_require(self):
        yaml = """
        !define double: !fn
          !require x: "value to double"
          !fn : ${int(x) * 2}

        result: !double 21
        """
        cfg = loads(yaml)
        resolve_all_lazy(cfg)
        assert cfg["result"] == 42

    def test_scalar_and_mapping_form_agree(self):
        scalar = """
        !define double: !fn
          !require x: "v"
          !fn : ${int(x) * 2}
        result: !double 21
        """
        mapping = """
        !define double: !fn
          !require x: "v"
          !fn : ${int(x) * 2}
        result: !double { x: 21 }
        """
        sc = loads(scalar); resolve_all_lazy(sc)
        mp = loads(mapping); resolve_all_lazy(mp)
        assert sc["result"] == mp["result"] == 42

    def test_scalar_binds_first_when_multiple_requires(self):
        yaml = """
        !define files_under: !fn
          !require sub: "subdir"
          !set_default ext: "yaml"
          path: "/root/${sub}.${ext}"

        result: !files_under L0
        """
        cfg = loads(yaml)
        resolve_all_lazy(cfg)
        assert cfg["result"]["path"] == "/root/L0.yaml"

    def test_scalar_too_many_positionals_raises(self):
        """Scalar tag invocation can't supply more than one positional; that's
        a no-op edge case (tag scalar is one value). The TypeError is for
        symmetry with Python -- direct Python-side calls with too many args."""
        from dracon.symbols import CallableSymbol
        yaml = """
        !define f: !fn
          !require a: "..."
        sym: ${f}
        """
        cfg = loads(yaml)
        resolve_all_lazy(cfg)
        sym = cfg["sym"]
        assert isinstance(sym, CallableSymbol)
        with pytest.raises(TypeError):
            sym(1, 2)

    def test_pipe_scalar_positional_threads_through(self):
        yaml = """
        !define double: !fn
          !require x: "..."
          !fn : ${int(x) * 2}

        !define add_one: !fn
          !require x: "..."
          !fn : ${int(x) + 1}

        !define pipeline: !pipe
          - !fn:double
          - !fn:add_one

        result: !pipeline 10
        """
        cfg = loads(yaml)
        resolve_all_lazy(cfg)
        assert cfg["result"] == 21


# ────────────────────────────────────────────────────────────────────────────
# call-site @/path kwargs resolve against caller root, not kwargs mapping
# ────────────────────────────────────────────────────────────────────────────


class TestCallSiteAtPathKwargs:
    def test_atpath_kwarg_resolves_against_caller_root(self):
        yaml = """
        !define Block: !fn
          !require name: "..."
          !require caller_name: "..."
          endpoint: "https://${name}.example.com"
          ref_to_caller: ${caller_name}

        service:
          name: api
          obs: !Block
            name: ${@/service.name}
            caller_name: ${@/service.name}
        """
        cfg = loads(yaml)
        resolve_all_lazy(cfg)
        obs = dict(cfg["service"]["obs"])
        assert obs["endpoint"] == "https://api.example.com"
        assert obs["ref_to_caller"] == "api"

    def test_kwarg_atpath_for_nested_value(self):
        """The kwarg value can also be a nested mapping with @/path inside."""
        yaml = """
        !define Block: !fn
          !require cfg: "..."
          mirrored: ${cfg}

        root:
          val: hello
          out: !Block
            cfg:
              copy: ${@/root.val}
        """
        cfg = loads(yaml)
        resolve_all_lazy(cfg)
        assert cfg["root"]["out"]["mirrored"]["copy"] == "hello"

    def test_atpath_scalar_arg_resolves_against_caller_root(self):
        """The same fix should hold for the scalar tag-form: when the scalar
        arg is itself an `@/abs.path` expression, it must resolve against the
        caller's tree."""
        yaml = """
        !define square: !fn
          !require x: "..."
          !fn : ${int(x) ** 2}

        service:
          n: 5
          sq: !square ${@/service.n}
        """
        cfg = loads(yaml)
        resolve_all_lazy(cfg)
        assert cfg["service"]["sq"] == 25

    def test_atpath_kwarg_to_fn_target_partial(self):
        """`!fn:target` partials should resolve `@/path` kwargs at the call
        site -- mirrors the template-tag path through the same
        `_construct_kwargs` choke point."""
        from dracon.loader import DraconLoader
        from dracon.symbols import CallableSymbol

        def join(name: str, suffix: str) -> str:
            return f"{name}-{suffix}"

        loader = DraconLoader(context={'join': join})
        cfg = loader.loads("""
        service:
          name: api
          partial: !fn:join
            name: ${@/service.name}
            suffix: prod
        """)
        cfg.resolve_all_lazy()
        partial = cfg["service"]["partial"]
        assert isinstance(partial, CallableSymbol)
        assert dict(partial._kwargs) == {"name": "api", "suffix": "prod"}

    def test_kwarg_atpath_and_compose_time_define_agree(self):
        """The compose-time !define workaround and the @/path call-site form
        should produce the same result."""
        kwarg = """
        !define Block: !fn
          !require caller_name: "..."
          ref: ${caller_name}

        service:
          name: api
          obs: !Block
            caller_name: ${@/service.name}
        """
        define = """
        !define svc_name: api

        !define Block: !fn
          !require caller_name: "..."
          ref: ${caller_name}

        service:
          name: ${svc_name}
          obs: !Block
            caller_name: ${svc_name}
        """
        a = loads(kwarg); resolve_all_lazy(a)
        b = loads(define); resolve_all_lazy(b)
        assert a["service"]["obs"]["ref"] == b["service"]["obs"]["ref"] == "api"
