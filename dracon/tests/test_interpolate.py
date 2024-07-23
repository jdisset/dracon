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

from dracon.interpolation import (
    outermost_interpolation_exprs,
    find_first_occurence,
    find_keypaths,
    resolve_keypath,
    resolve_eval_str,
    LazyInterpolable,
)

from pydantic.dataclasses import dataclass
from dracon.keypath import KeyPath
from typing import Any, Dict, Callable, Optional, Tuple, List
import copy
from dracon.utils import DictLike, ListLike
from asteval import Interpreter
##────────────────────────────────────────────────────────────────────────────}}}

def test_dict():
    kp = find_keypaths(
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

    interp_matches = outermost_interpolation_exprs(test_expr2)


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

    KeyPath('/nested.inner/name').get_obj(obj)


    g = resolve_eval_str(obj['nested']['inner']['greeting'], '/nested.inner.other', obj)
    assert g == 'greetings, John!'

    l = resolve_eval_str(obj['nested']['inner']['list'], '/nested.inner.match', obj)
    assert l == ['John_0', 'John_1', 'John_2', 'John_3', 'John_4']

    # r = resolve_eval_str(obj['nested']['inner']['ref'], '/nested.inner.ref', obj)
    # ^^^ this won't work with a normal dict because there is a change of current path in the reference.
    # It should work with a Dracontainer because accessing the member should trigger resolution

def test_lazy():

    obj = {
        "name": "John",
        "n": 5,
        "greetingroot": "Hello, ${@name}!",
        'nested': {
            'inner': {
                'greeting': 'greetings, ${"dear "+  @/name}!',
                'list': '${[@/name + "_" + str(i) for i in range(@/n)]}',
                'ref': '${@/greetingroot}',
            }
        },
    }

    loader = DraconLoader()
    ymldump = loader.dump(obj)
    print(ymldump)

    loaded = loader.loads(ymldump)
    loaded.name
    assert loaded.name == 'John'
    loaded.greetingroot
    assert loaded.greetingroot == 'Hello, John!'
    assert loaded.nested.inner.greeting == 'greetings, dear John!'
    assert loaded.nested.inner.ref == 'Hello, John!'

    assert loaded.nested.inner._dracon_current_path == KeyPath('/nested.inner')

    newstr = '${@/name + " " + @/nested.inner.greeting}'
    loaded.nested.inner['new'] = newstr
    assert loaded.nested.inner.new == newstr
    loaded.nested.inner['new'] = LazyInterpolable(loaded.nested.inner['new'])
    assert (loaded.nested.inner.new == 'John greetings, dear John!')

