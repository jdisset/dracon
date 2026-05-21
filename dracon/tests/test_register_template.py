# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
"""Step 05 tests: `_params_from_callable` polish + `register_template` convenience.

Polish lives in `_params_from_callable` (docstring per-param help, mutable-default
snapshot) so it benefits every plain callable in scope. `register_template` is a
thin convenience around `loader.context[name] = fn` that enforces template policy
(no *args; **kwargs opt-in) and accepts explicit `name=` / `loader=` overrides.
"""

from __future__ import annotations

import pytest

import dracon as dr
from dracon.symbols import CallableSymbol, _params_from_callable


def plot_smooth_2d(*, draw_colorbar=True, xlims=(0.0, 1.0), cmap="viridis"):
    """Plot a 2D smooth heatmap.

    Parameters
    ----------
    draw_colorbar : bool
        Whether to show the colorbar.
    xlims : tuple[float, float]
        Axis limits.
    cmap : str
        Colormap name.
    """
    return {'draw_colorbar': draw_colorbar, 'xlims': xlims, 'cmap': cmap}


def google_style(port=8080, host="localhost"):
    """Start a server.

    Args:
        port (int): TCP port to bind.
        host: Network interface.
    """
    return (host, port)


# ── _params_from_callable polish: applies to every plain callable ──────────

class TestParamsFromCallablePolish:
    def test_numpy_style_docstring_attached(self):
        params = _params_from_callable(plot_smooth_2d)
        by_name = {p.name: p for p in params}
        assert "colorbar" in (by_name['draw_colorbar'].docs or "").lower()
        assert "axis limits" in (by_name['xlims'].docs or "").lower()
        assert "colormap" in (by_name['cmap'].docs or "").lower()

    def test_google_style_docstring_attached(self):
        params = _params_from_callable(google_style)
        by_name = {p.name: p for p in params}
        assert "tcp port" in (by_name['port'].docs or "").lower()
        assert "network interface" in (by_name['host'].docs or "").lower()

    def test_no_docstring_yields_no_docs(self):
        def bare(x=1): return x
        params = _params_from_callable(bare)
        assert params[0].docs is None

    def test_mutable_list_default_is_snapshotted(self):
        shared = [1, 2, 3]
        def f(items=shared):
            return items
        params = _params_from_callable(f)
        snap = params[0].default
        assert snap == [1, 2, 3]
        snap.append(99)
        # the original signature default should be untouched
        import inspect
        live = inspect.signature(f).parameters['items'].default
        assert live == [1, 2, 3]

    def test_mutable_dict_default_is_snapshotted(self):
        shared = {'a': 1}
        def f(d=shared): return d
        params = _params_from_callable(f)
        params[0].default['b'] = 2
        assert shared == {'a': 1}


# ── register_template convenience ────────────────────────────────────────

class TestRegisterTemplate:
    def test_register_surfaces_params(self):
        loader = dr.DraconLoader()
        sym = dr.register_template(plot_smooth_2d, loader=loader)
        iface = sym.interface()
        names = {p.name for p in iface.params}
        assert names == {'draw_colorbar', 'xlims', 'cmap'}

    def test_register_returns_callable_symbol(self):
        loader = dr.DraconLoader()
        sym = dr.register_template(plot_smooth_2d, loader=loader)
        assert isinstance(sym, CallableSymbol)

    def test_register_pulls_docstring_help(self):
        loader = dr.DraconLoader()
        sym = dr.register_template(plot_smooth_2d, loader=loader)
        p = next(p for p in sym.interface().params if p.name == 'draw_colorbar')
        assert p.docs and "colorbar" in p.docs.lower()

    def test_register_with_explicit_name(self):
        loader = dr.DraconLoader()
        dr.register_template(plot_smooth_2d, name='plot', loader=loader)
        assert 'plot' in loader.context

    def test_register_default_name(self):
        loader = dr.DraconLoader()
        dr.register_template(plot_smooth_2d, loader=loader)
        assert 'plot_smooth_2d' in loader.context

    def test_register_rejects_varargs(self):
        def bad(*args, **kwargs): pass
        with pytest.raises(ValueError, match=r"\*args"):
            dr.register_template(bad)

    def test_register_rejects_kwargs_by_default(self):
        def variadic(x=1, **kwargs): return (x, kwargs)
        with pytest.raises(ValueError, match=r"\*\*kwargs"):
            dr.register_template(variadic)

    def test_register_allows_kwargs_with_opt_in(self):
        def variadic(x=1, **kwargs): return (x, kwargs)
        sym = dr.register_template(variadic, allow_extras=True)
        assert sym(x=2, y=3) == (2, {'y': 3})

    def test_reregister_replaces(self):
        def serve(port=8080): pass
        def serve_v2(port=9090, debug=False): pass
        loader = dr.DraconLoader()
        dr.register_template(serve, name='serve', loader=loader)
        dr.register_template(serve_v2, name='serve', loader=loader)
        sym = loader.context.lookup_symbol('serve')
        assert {p.name for p in sym.interface().params} == {'port', 'debug'}

    def test_yaml_uses_registered_symbol(self):
        loader = dr.DraconLoader()
        dr.register_template(plot_smooth_2d, loader=loader)
        cfg = loader.loads("plot: !fn:plot_smooth_2d\n  draw_colorbar: false\n")
        # `plot` is a bound symbol with draw_colorbar pinned to False
        assert cfg['plot'](xlims=(0, 1), cmap='magma') == {
            'draw_colorbar': False, 'xlims': (0, 1), 'cmap': 'magma',
        }


# ── py-loader @defaults selector ────────────────────────────────────────

class TestDefaultsViaIncludePy:
    def test_defaults_selector_returns_kwarg_defaults(self):
        loader = dr.DraconLoader()
        cfg = loader.loads(
            "plot_config: !include py:dracon.tests.test_register_template.plot_smooth_2d@defaults\n"
        )
        assert cfg['plot_config'] == {
            'draw_colorbar': True, 'xlims': (0.0, 1.0), 'cmap': 'viridis',
        }

    def test_defaults_compose_into_mapping_override(self):
        loader = dr.DraconLoader()
        yaml_src = (
            "plot_config:\n"
            "  <<: !include py:dracon.tests.test_register_template.plot_smooth_2d@defaults\n"
            "  draw_colorbar: false\n"
        )
        cfg = loader.loads(yaml_src)
        assert cfg['plot_config'] == {
            'draw_colorbar': False, 'xlims': (0.0, 1.0), 'cmap': 'viridis',
        }
