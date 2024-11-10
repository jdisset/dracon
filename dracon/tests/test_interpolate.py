## {{{                          --     imports     --
from dracon.loader import DraconLoader
from dracon.dracontainer import Mapping
from pydantic import BaseModel
from dracon.interpolation import outermost_interpolation_exprs
from dracon.lazy import LazyInterpolable
from dracon.keypath import KeyPath
import copy
from dracon.interpolation_utils import find_field_references
from dracon.include import compose_from_include_str
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
        r"@/name.greeting..back+2 + / @path.to.list[2] = @haha./../p\[3{]"
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

    loader = DraconLoader(enable_interpolation=True, context={'ClassA': ClassA})
    loader.yaml.representer.full_module_path = False
    config = loader.loads(yaml_content)
    config.resolve_all_lazy()

    assert '__dracon__' not in config
    assert isinstance(config['obj4'], ClassA)
    assert config['obj4'].index == 4
    assert config['obj4'].name == 'Name 4'
    assert config['prop4'] == '4: Name 4'

    assert config['as_ampersand_anchor'] == [
        ClassA(index=1, name='Name 1'),
        ClassA(index=2, name='Name 2'),
        ClassA(index=3, name='Name 3'),
        ClassA(index=4, name='Name 4'),
        ClassA(index=5, name='Name 5'),
    ]


def test_instruction_define():
    yaml_content = """
    !define i : ${4}

    a: ${i + 2}
    """
    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)
    config.resolve_all_lazy()

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


def test_instruction_if_true():
    yaml_content = """
    !if 1:
      a: 1
      b: 2
      !if ${True}:
        c: 3
        !if null:
            d: 4
        !if 1:
            e: 5
        !if true:
            f: 6
        !if false:
            g: 7
        !if ${False}:
            h: 8
        !if ${True }:
            i: 9
        !if 0:
            j: 10
        !if 2:
            k: 11
    """
    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)
    config.resolve_all_lazy()

    print(config)
    assert config == {
        'a': 1,
        'b': 2,
        'c': 3,
        'e': 5,
        'f': 6,
        'i': 9,
        'k': 11,
    }


def test_instruction_if_false():
    yaml_content = """
    !if ${False}:
      a: 1
      b: 2
    c: 3
    """
    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)
    config.resolve_all_lazy()

    assert 'a' not in config
    assert 'b' not in config
    assert 'c' in config
    assert config.c == 3


def test_instruction_if_inside_each():
    yaml_content = """
    numbers:
      !each(n) ${list(range(5))}:
        - !if ${(n % 2) == 0}:
            number: ${n}
    """
    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)
    config.resolve_all_lazy()

    expected_numbers = [{'number': 0}, {'number': 2}, {'number': 4}]
    assert config.numbers == expected_numbers


def test_instruction_if_sequence():
    yaml_content = """
    !define threshold: ${10}
    !define val: ${15}
    list:
        - !if ${val > threshold}: "greater"
        - !if ${val > threshold}:
            a: 1
            !if 1:
                b: 2
        - !if ${val <= threshold}: "lessthan"
        - other
    """

    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)
    config.resolve_all_lazy()

    assert config.list == [
        "greater",
        {'a': 1, 'b': 2},
        "other",
    ]


def test_instruction_if_complex_expression_true():
    yaml_content = """
    !define threshold: ${10}
    !define value: ${15}
    !if ${value > threshold}:
      result: "greater"
    !if ${value <= threshold}:
      result: "lessthan"
    """
    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)
    config.resolve_all_lazy()

    assert 'result' in config
    assert config.result == "greater"


def test_instruction_if_with_external_function():
    yaml_content = """
    !define is_even: ${is_even_function(4)}
    !if ${is_even}:
      number_type: "Even"
    !if ${not is_even}:
      number_type: "Odd"
    """

    def is_even_function(n):
        return n % 2 == 0

    loader = DraconLoader(enable_interpolation=True, context={'is_even_function': is_even_function})
    config = loader.loads(yaml_content)
    config.resolve_all_lazy()

    assert 'number_type' in config
    assert config.number_type == "Even"


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

    loader = DraconLoader(enable_interpolation=True, context={'ClassA': ClassA})
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

    loader = DraconLoader(enable_interpolation=True, context={'ClassA': ClassA})
    loader.yaml.representer.full_module_path = False
    config = loader.loads(yaml_content)
    config.resolve_all_lazy()

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


def test_defines():
    yaml_content = """
    !define i42 : !int 42

    expr42: !int ${i42}
    inc42: *$i42

    !define compint: ${4 + 4}
    compint_expr: ${compint}
    compint_inc: !include $compint

    !define runtimeval : ${func(1,2)}
    runtimeval_expr: ${runtimeval}

    !define recursive_def: ${&runtimeval_expr}
    recursive: ${recursive_def.evaluate()}

    a_obj: !ClassA
        index: &aid ${i42}
        name: oldname
        <<{<+}: 
            name: "new_name ${&aid}"

    nested:
        !define aid: ${get_index(construct(&/a_obj))}
        a_index: ${aid}
        aname: ${&/a_obj.name}
        constructed_name: ${construct(&/a_obj).name}
        constructed_nameindex: ${construct(&/a_obj).name_index}

    """

    loader = DraconLoader(enable_interpolation=True, context={'ClassA': ClassA})
    loader.yaml.representer.full_module_path = False
    loader.context['func'] = lambda x, y: x + y
    loader.context['get_index'] = lambda obj: obj.index
    config = loader.loads(yaml_content)
    config.resolve_all_lazy()

    assert config['expr42'] == 42
    assert config['inc42'] == 42
    assert config['compint_expr'] == 8
    assert config['compint_inc'] == 8
    assert config['runtimeval_expr'] == 3

    assert config['recursive'] == 3

    assert isinstance(config.a_obj, ClassA)
    assert config['a_obj'].index == 42
    assert config['a_obj'].name == "new_name 42"

    assert config['nested']['a_index'] == config['a_obj'].index
    assert config['nested']['aname'] == config['a_obj'].name

    assert config['nested']['constructed_name'] == config['a_obj'].name
    assert config['nested']['constructed_nameindex'] == config['a_obj'].name_index


def test_include():
    loader = DraconLoader(enable_interpolation=True, context={'ClassA': ClassA})
    loader.context['get_index'] = lambda obj: obj.index
    loader.context['get_nameindex'] = lambda obj: obj.name_index
    compres = compose_from_include_str(loader, 'pkg:dracon:tests/configs/interp_include.yaml')
    config = loader.load_composition_result(compres)
    config.resolve_all_lazy()
    assert config.nested.a_index == 2

    assert isinstance(config.nested.a_nested, ClassA)
    assert config.nested.a_nested.index == 3
    assert config.nested.oldname == 'oldname 2'

    assert config.nested.a_nested.name == 'newer_name 3'

    assert config.nested.nameindex == '3: oldname 3'
    assert config.nested.nameindex_2 == '3: oldname 3'

    assert config.nested.alist == [ClassA(index=1, name='name 1'), ClassA(index=2, name='name 2')]

    assert config.other.a == 3
    assert config.other.var_b_value == 15
