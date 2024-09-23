## {{{                          --     imports     --
import re
import pytest
from dracon import dump, loads
from dracon.loader import DraconLoader
from dracon.dracontainer import Dracontainer, Mapping, Sequence
from dracon.interpolation import InterpolationError, InterpolationMatch
from typing import Generic, TypeVar, Any, Optional, Annotated, cast, List
from pydantic import (
    BaseModel,
    field_validator,
    BeforeValidator,
    WrapValidator,
    AfterValidator,
    ConfigDict,
    Field,
)

from dracon.interpolation import outermost_interpolation_exprs
from dracon.lazy import LazyInterpolable

from pydantic.dataclasses import dataclass
from dracon.keypath import KeyPath
from typing import Any, Dict, Callable, Optional, Tuple, List
import copy
from dracon.interpolation_utils import find_field_references
from asteval import Interpreter
##────────────────────────────────────────────────────────────────────────────}}}


class ClassA(BaseModel):
    index: int
    name: str = ''

    @property
    def name_index(self):
        return f"{self.index}: {self.name}"


class ClassB(BaseModel):
    attr1: str
    attr2: int
    attrA: ClassA


def test_dict():
    kp = find_field_references(
        "@/name.greeting..back+2 + / @path.to.list[2] = @haha./../p\[3{]"
    )  # -> [ @/name.greeting..back ,  @path.to.list , @haha./../p\[3 ]

    assert len(kp) == 3
    assert kp[0].start == 0
    assert kp[0].end == 21
    assert kp[0].expr == "/name.greeting..back"

    assert kp[1].start == 28
    assert kp[1].end == 41
    assert kp[1].expr == "path.to.list"

    assert kp[2].start == 47
    assert kp[2].end == 61
    assert kp[2].expr == r"haha./../p[3"

    test_expr2 = "${@/name\\.greeting..back+2 + / @path.${'haha' + @inner.match }to.list\\[2] } = @haha./../p\\[3{] + ${2+2}"
    test_expr_paren = "$(@/name\\.greeting..back+2 + / @path.${'haha' + @inner.match }to.list\\[2] ) = @haha./../p\\[3{] + ${2+2}"

    interp_matches = outermost_interpolation_exprs(test_expr2)
    assert len(interp_matches) == 2
    assert interp_matches[0].start == 0

    interp_matches = outermost_interpolation_exprs(test_expr_paren)
    assert len(interp_matches) == 2
    print(interp_matches)
    assert interp_matches[0].start == 0

    obj = {
        "name": "John",
        "n": 5,
        "greetingroot": "Hello, ${@name}!",
        'nested': {
            'inner': {
                'greeting': 'greetings, ${@/name}!',
                'list': '${[@/name + "_" + str(i) for i in range(@/n)]}',
                'ref': '${@/greetingroot}',
            }
        },
    }

    dump = DraconLoader().dump(obj)
    loader = DraconLoader(enable_interpolation=True)
    loaded = loader.loads(dump)
    loaded.resolve_all_lazy()

    assert loaded.name == 'John'
    assert loaded.greetingroot == 'Hello, John!'
    assert loaded.nested.inner.greeting == 'greetings, John!'
    assert loaded.nested.inner.ref == 'Hello, John!'
    assert loaded.nested.inner.list == ['John_0', 'John_1', 'John_2', 'John_3', 'John_4']


def test_lazy():
    obj = {
        "name": "John",
        "n": 5,
        "greetingroot": "Hello, ${@name}!",
        "quatre": "${2+2}",
        'nested': {
            'inner': {
                'greeting': 'greetings, ${"dear "+  @/name}!',
                'list': '${[@/name + "_" + str(i) for i in range(@....n)]}',
                'ref': '${@/greetingroot}',
            }
        },
    }

    loader = DraconLoader(enable_interpolation=True)
    ymldump = loader.dump(obj)

    print(ymldump)

    loaded = loader.loads(ymldump)
    loaded_copy = copy.copy(loaded)
    loaded_deepcopy = copy.deepcopy(loaded)

    assert isinstance(loaded, Mapping)
    assert isinstance(loaded_copy, Mapping)
    assert isinstance(loaded_deepcopy, Mapping)

    assert loaded.name == 'John'
    assert loaded.quatre == 4

    assert isinstance(loaded._data['greetingroot'], LazyInterpolable)
    assert loaded.greetingroot == 'Hello, John!'
    assert isinstance(loaded._data['greetingroot'], str)
    assert isinstance(loaded_copy._data['greetingroot'], str)
    assert isinstance(loaded_deepcopy._data['greetingroot'], LazyInterpolable)

    assert loaded.nested.inner.greeting == 'greetings, dear John!'
    assert loaded.nested.inner.ref == 'Hello, John!'
    assert loaded.nested.inner.list == ['John_0', 'John_1', 'John_2', 'John_3', 'John_4']

    assert loaded.nested.inner._dracon_current_path == KeyPath('/nested.inner')

    newstr = '${@/name + " " + @/nested.inner.greeting}'
    loaded.nested.inner['new'] = newstr
    assert loaded.nested.inner.new == newstr
    loaded.nested.inner['new'] = LazyInterpolable(loaded.nested.inner['new'])
    assert loaded.nested.inner.new == 'John greetings, dear John!'


def test_ampersand_interpolation_simple():
    yaml_content = """
    base: &base_anchor
      key1: value1
      key2: value2

    config:
      key3: ${&/base}
      key4: ${&/base.key1}
      full: ${&base_anchor}
      key1_amp: ${&base_anchor.key1}
      key1_at: ${@/base.key1}
    """

    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)

    config_copy = copy.deepcopy(config)

    assert config['config']['key3'] == {'key1': 'value1', 'key2': 'value2'}
    assert config['config']['full'] == {'key1': 'value1', 'key2': 'value2'}
    assert config['config']['key4'] == 'value1'
    assert config['config']['key1_amp'] == 'value1'
    assert config['config']['key1_at'] == 'value1'

    config_copy.base.key1 = 'new_value1'
    assert config_copy['config']['key3'] == {'key1': 'value1', 'key2': 'value2'}
    assert config_copy['config']['full'] == {'key1': 'value1', 'key2': 'value2'}
    assert config_copy['config']['key4'] == 'value1'
    assert config_copy['config']['key1_amp'] == 'value1'
    assert config_copy['config']['key1_at'] == 'new_value1'


# 6.5
# removed deepcopy in merge -> 4.6


def test_recursive_interpolation():
    yaml_content = """
    base: &base_anchor
        key1: value1
        key2: ${@key1}
        key3: ${&key2}
        key4: ${@key3}
        key5: ${&key4}
        key6: ${&key5}
        key7: ${&base_anchor.key6}
        key8: ${@/base.key7}

    base2: ${&base_anchor}
    base3: ${&base2}
    base4: ${&/base3}
    base5: ${@base4}
    base6: ${@/base}
    """

    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)
    config.resolve_all_lazy()

    assert config['base'] == {
        'key1': 'value1',
        'key2': 'value1',
        'key3': 'value1',
        'key4': 'value1',
        'key5': 'value1',
        'key6': 'value1',
        'key7': 'value1',
        'key8': 'value1',
    }

    assert config['base2'] == config['base']
    assert config['base3'] == config['base']
    assert config['base4'] == config['base']
    assert config['base5'] == config['base']
    assert config['base6'] == config['base']


def test_ampersand_interpolation_complex():
    yaml_content = """
        __dracon__:
          simple_obj: &smpl
            index: ${i + 1}
            name: "Name ${&index}"

        all_objs: ${[&/__dracon__.simple_obj:i=j for j in range(5)]}
        all_objs_by_anchor: ${[&smpl:i=i for i in range(5)]}
    """

    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)
    config.resolve_all_lazy()
    assert '__dracon__' not in config

    assert config['all_objs'] == [
        {'index': 1, 'name': 'Name 1'},
        {'index': 2, 'name': 'Name 2'},
        {'index': 3, 'name': 'Name 3'},
        {'index': 4, 'name': 'Name 4'},
        {'index': 5, 'name': 'Name 5'},
    ]
    assert config['all_objs_by_anchor'] == config['all_objs']


def test_obj_references():
    yaml_content = """
    __dracon__:
        simple_obj: &smpl !ClassA
            index: ${i + 1}
            name: "Name ${@index}"

    obj4: &o4 ${&smpl:i=3}
    prop4: ${@obj4.name_index}

    as_ampersand_anchor: ${[&smpl:i=i for i in range(5)]}
    """

    loader = DraconLoader(enable_interpolation=True)
    loader.yaml.representer.full_module_path = False
    config = loader.loads(yaml_content)
    config.resolve_all_lazy()

    assert '__dracon__' not in config
    assert isinstance(config['obj4'], ClassA)
    assert config['obj4'].index == 4
    assert config['obj4'].name == 'Name 4'
    assert config['prop4'] == '4: Name 4'

    assert config['as_ampersand_anchor'] == [
        {'index': 1, 'name': 'Name 1'},
        {'index': 2, 'name': 'Name 2'},
        {'index': 3, 'name': 'Name 3'},
        {'index': 4, 'name': 'Name 4'},
        {'index': 5, 'name': 'Name 5'},
    ]


def test_instruction_define():
    yaml_content = """
    !define i : ${4}

    a: ${i + 2}
    """
    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)
    config.resolve_all_lazy()

    print(config)
    assert config.a == 6


def test_instruction_each_simple():
    yaml_content = """
    ilist:
        !each(e) ${list(range(5))}:
            - ${e}
    """
    loader = DraconLoader(enable_interpolation=True)
    composed = loader.compose_config_from_str(yaml_content)

    config = loader.loads(yaml_content)

    assert '__dracon__' not in config
    assert len(config['ilist']) == 5

    config.resolve_all_lazy()


def test_obj_references_instruct():
    yaml_content = """
    __dracon__:
        simple_obj: &smpl !ClassA
            index: ${i + 1}
            name: "Name ${@index}"

    obj4: &o4 ${&smpl:i=3}
    prop4: ${@obj4.name_index}

    # using each + define
    as_ampersand_anchor:
        !each(i) ${range(5)}:
            - ${&smpl:i=i}

    """

    loader = DraconLoader(enable_interpolation=True)
    loader.yaml.representer.full_module_path = False
    config = loader.loads(yaml_content)
    config.resolve_all_lazy()

    assert '__dracon__' not in config
    assert isinstance(config['obj4'], ClassA)
    assert config['obj4'].index == 4
    assert config['obj4'].name == 'Name 4'
    assert config['prop4'] == '4: Name 4'

    manual_list = [ClassA(index=i + 1, name=f"Name {i+1}") for i in range(5)]
    assert config['as_ampersand_anchor'] == manual_list


def test_instruct_on_nodes():
    yaml_content = """
    a_list: &alist
     - !ClassA
       index: 42
     - !ClassA
       index: 43
     - !ClassA
       index: 44

    !define i42 : 42

    list42:
        !each(elt) ${&alist}:
            - <<: *$elt
              <<{+}: {name: "new_name ${@index}"}
              <<{<+}:
                index: *$i42

    other_list:
        !each(elt) ${&alist}:
            - <<: *$elt
              <<{+}: {name: "new_name ${@index}"}
              <<{<+}: 
                index: !include $elt@index

    """

    loader = DraconLoader(enable_interpolation=True)
    loader.yaml.representer.full_module_path = False
    config = loader.loads(yaml_content)
    config.resolve_all_lazy()
    print(config)
    print(f"{config['other_list']=}")

    assert config['list42'] == [
        ClassA(index=42, name='new_name 42'),
        ClassA(index=42, name='new_name 42'),
        ClassA(index=42, name='new_name 42'),
    ]

    assert config['other_list'] == [
        ClassA(index=42, name='new_name 42'),
        ClassA(index=43, name='new_name 43'),
        ClassA(index=44, name='new_name 44'),
    ]

