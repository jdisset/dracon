# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

import pytest
from io import StringIO

from dracon import DraconLoader
from dracon.yaml import PicklableYAML


@pytest.fixture
def loader():
    return DraconLoader(
        context={
            'add': lambda a, b: a + b,
            'sum_': lambda *a: sum(a),
            'mkdict': dict,
            'x': 10,
            'y': 20,
            'z': 30,
            'tag': 'v1',
        }
    )


@pytest.mark.parametrize(
    'src,expected',
    [
        ('items: [${add(1, 2)}, ${x}]', {'items': [3, 10]}),
        ('items: [${sum_(1, 2, 3, 4)}]', {'items': [10]}),
        ('m: {a: ${x}, b: ${y}}', {'m': {'a': 10, 'b': 20}}),
        ('m: {a: ${add(x, y)}, b: ${sum_(x, y, z)}}', {'m': {'a': 30, 'b': 60}}),
        ('a: ${sum_(1, 2, 3)}', {'a': 6}),
        (
            'nested: [${add(1, 2)}, [${x}, ${y}], {k: ${z}}]',
            {'nested': [3, [10, 20], {'k': 30}]},
        ),
        ('grid: [[${x}, ${y}], [${y}, ${z}]]', {'grid': [[10, 20], [20, 30]]}),
        ('t: ${(x, y, z)}', {'t': (10, 20, 30)}),
        ('p: ${(x,)}', {'p': (10,)}),
    ],
)
def test_flow_context_with_interpolation(loader, src, expected):
    out = loader.loads(src)
    assert _to_plain(out) == expected


def test_dict_literal_inside_interpolation(loader):
    out = loader.loads('cfg: ${mkdict({"k": x, "k2": y})}')
    assert _to_plain(out) == {'cfg': {'k': 10, 'k2': 20}}


def test_dict_literal_inside_flow_mapping(loader):
    out = loader.loads('cfg: {payload: ${mkdict({"k": x, "k2": y})}}')
    assert _to_plain(out) == {'cfg': {'payload': {'k': 10, 'k2': 20}}}


def test_deep_nesting(loader):
    out = loader.loads('v: ${mkdict({"outer": mkdict({"inner": [x, y, z]})})}')
    assert _to_plain(out) == {'v': {'outer': {'inner': [10, 20, 30]}}}


def test_string_with_braces_inside_interpolation(loader):
    out = loader.loads('s: ${"a}b" + ","}')
    assert _to_plain(out) == {'s': 'a}b,'}


def test_string_with_brackets_inside_interpolation(loader):
    out = loader.loads('s: [${"]" + ","}]')
    assert _to_plain(out) == {'s': ['],']}


def test_block_context_still_works(loader):
    out = loader.loads('a: ${add(1, 2)}\nb: ${x}\n')
    assert _to_plain(out) == {'a': 3, 'b': 10}


def test_paren_form_in_flow(loader):
    out = loader.loads('items: [$(add(1, 2)), $(x)]')
    assert _to_plain(out) == {'items': [3, 10]}


def test_escaped_dollar_brace_stays_literal(loader):
    out = loader.loads(r"items: [a, '\${x}']")
    assert _to_plain(out) == {'items': ['a', '${x}']}


def test_double_dollar_escape(loader):
    out = loader.loads('items: ["$${x}"]')
    assert _to_plain(out) == {'items': ['${x}']}


def test_tag_with_interpolation_in_flow(loader):
    out = loader.loads('vals: [!int "${x}", !int "${y}"]')
    assert _to_plain(out) == {'vals': [10, 20]}


def test_unbalanced_interpolation_falls_back(loader):
    out = loader.loads('a: hello\nb: world\n')
    assert _to_plain(out) == {'a': 'hello', 'b': 'world'}


def test_interpolation_at_start_of_flow_value(loader):
    out = loader.loads('m: {k: ${add(x, y)}}')
    assert _to_plain(out) == {'m': {'k': 30}}


def test_multi_doc_with_flow_interpolation(loader):
    src = 'a: ${x}\n---\nb: [${y}, ${z}]\n'
    docs = list(loader.yaml.load_all(StringIO(src)))
    assert len(docs) == 2


def test_round_trip_dump_preserves_flow_interpolation():
    yml = PicklableYAML()
    src = 'items: [${add(1, 2)}, ${other}]\n'
    data = yml.load(src)
    buf = StringIO()
    yml.dump(data, buf)
    out = buf.getvalue()
    assert '${add(1, 2)}' in out
    assert '${other}' in out


def test_interpolation_inside_quoted_scalar_untouched(loader):
    out = loader.loads('items: ["literal ${x}", "${x}"]')
    assert _to_plain(out) == {'items': ['literal 10', 10]}


def _to_plain(value):
    if hasattr(value, 'items'):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)) and not isinstance(value, str):
        cls = type(value) if isinstance(value, tuple) else list
        items = [_to_plain(v) for v in value]
        return cls(items) if cls is tuple else items
    if hasattr(value, '__iter__') and not isinstance(value, str) and hasattr(value, '__getitem__'):
        return [_to_plain(v) for v in value]
    return value
