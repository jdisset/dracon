## {{{                          --     imports     --
import re
import pytest
from dracon.interpolation import InterpolationError, InterpolationMatch
from dracon.interpolation import (
    outermost_interpolation_exprs,
    find_first_occurence,
    find_keypaths,
)
from pydantic.dataclasses import dataclass
from dracon.keypath import KeyPath
from typing import Any, Dict, Callable, Optional, Tuple, List
import copy
from dracon.utils import DictLike, ListLike
from asteval import Interpreter
##────────────────────────────────────────────────────────────────────────────}}}


root_obj = {"name": "John", "greeting": "Hello, ${@name}!"}

key_path = KeyPath("/greeting")  # path to the value we want to interpolate
value = key_path.get_obj(root_obj)

interp_matches = outermost_interpolation_exprs(value)
assert len(interp_matches) == 1

match = interp_matches[0]
assert match.start == 7
assert match.end == 15
assert match.expr == "${@name}"

expr = match.expr[2:-1]  # remove ${ and }

current_key_path = key_path.copy()

# types of expr:
# name
# path.to.key.from.here
# .also.from.here
# ..from.parent
# /from/root
# /path.to.list.2
# /path.to.list[2] # -> same as above
# some_function()
# some_function(litteral1, ${/path.to.key}, litteral2)
# [.path.to.key for _ in range(10)]

# solution: evaluate the expression, and add some
# my role here is just to find all path-like expressions, find them in the root_obj, and replace them with their values

# maybe I could even just replace at the string level into a function

# I need to transform paths into KeyPath objects, then do path.get_obj(root_obj)

# a.path.to.function() -> KeyPath("a.path.to.function").get_obj(root_obj)()
#

symbols = {}
safe_eval = Interpreter(user_symbols=symbols, max_string_length=1000)
safe_eval("@the.name.of.a.thing = 10")


NOT_ESCAPED_REGEX = r"(?<!\\)(?:\\\\)*"

INVALID_KEYPATH_CHARS = r'[]() ,:=+-*%<>!&|^~@#$?;{}"\'`'
KEYPATH_START_CHAR = "@"


@dataclass
class KeypathMatch:
    start: int
    end: int
    expr: str


def find_keypaths(expr: str) -> List[KeypathMatch]:
    # find unescaped keypaths, i.e strings that start with @
    # and contain only valid keypath characters (or escaped special characters, e.g \/ or \[)
    ...


find_keypaths(
    "@/name.greeting..back+2 + / @path.to.list[2] = @haha./../p\[3{]"
)  # -> [ @/name.greeting..back ,  @path.to.list , @haha./../p\[3 ]

## {{{                        --     other tests     --

# def test_nested_interpolation():
# data = {
# "user": {"name": "Alice", "age": 30},
# "message": "${user.name} is ${user.age} years old",
# }
# result = interpolate(data, KeyPath("/message"))
# assert result == "Alice is 30 years old"


# def test_interpolation_with_expressions():
# data = {"x": 5, "y": 3, "result": "The sum is ${x + y}"}
# result = interpolate(data, KeyPath("/result"))
# assert result == "The sum is 8"


# def test_interpolation_with_custom_function():
# def uppercase(s):
# return s.upper()

# data = {"name": "john", "upper_name": "${uppercase(name)}"}
# result = interpolate(data, KeyPath("/upper_name"), custom_functions={"uppercase": uppercase})
# assert result == "JOHN"


# def test_interpolation_with_list_index():
# data = {
# "fruits": ["apple", "banana", "cherry"],
# "favorite": "My favorite fruit is ${fruits[1]}",
# }
# result = interpolate(data, KeyPath("/favorite"))
# assert result == "My favorite fruit is banana"


# def test_interpolation_with_dict_key():
# data = {
# "person": {"name": "Emma", "age": 28},
# "info": "${person['name']} is ${person['age']} years old",
# }
# result = interpolate(data, KeyPath("/info"))
# assert result == "Emma is 28 years old"

# def test_interpolation_with_keypath():
# data = {
# "person": {"name": "Emma", "age": 28},
# "info": "${person.name} is ${person.age} years old",
# }
# result = interpolate(data, KeyPath("/info"))
# assert result == "Emma is 28 years old"

# def test_interpolation_with_root_path():
# data = {"a": {"b": {"c": 100}}, "d": {"e": "Value from root: ${/a.b.c}"}}
# result = interpolate(data, KeyPath("/d.e"))
# assert result == "Value from root: 100"


# def test_interpolation_with_relative_path():
# data = {"x": {"y": {"z": 200}, "result": "Value from parent: ${..y.z}"}}
# result = interpolate(data, KeyPath("/x.result"))
# assert result == "Value from parent: 200"


# def test_nested_interpolation_expressions():
# data = {"a": 5, "b": 3, "c": "${a + ${b * 2}}"}
# result = interpolate(data, KeyPath("/c"))
# assert result == 11
# assert isinstance(result, int)


# def test_interpolation_in_list():
# data = {"x": 10, "y": 20, "list": ["${x}", "${y}", "${x + y}"]}
# result = interpolate(data, KeyPath("/list"))
# assert result == [10, 20, 30]


# def test_interpolation_with_ternary_operator():
# data = {"x": 15, "result": "${x > 10 if 'big' else 'small'}"}
# result = interpolate(data, KeyPath("/result"))
# assert result == "big"


# def test_interpolation_with_string_methods():
# data = {"text": "hello", "upper": "${text.upper()}"}
# result = interpolate(data, KeyPath("/upper"))
# assert result == "HELLO"


# def test_interpolation_error_undefined_variable():
# data = {"result": "${undefined_var}"}
# with pytest.raises(InterpolationError):
# interpolate(data, KeyPath("/result"))


# def test_interpolation_error_unsafe_operation():
# data = {"result": "${__import__('os').system('ls')}"}
# with pytest.raises(ValueError, match="Unsafe operation in expression"):
# interpolate(data, KeyPath("/result"))


# def test_no_interpolation_needed():
# data = {"simple": "No interpolation here"}
# result = interpolate(data, KeyPath("/simple"))
# assert result == "No interpolation here"
# full_result = interpolate(data, KeyPath("/"))
# assert full_result == {"simple": "No interpolation here"}


# def test_escape_interpolation():
# data = {"escaped": "This is not interpolated: $${name}"}
# result = interpolate(data, KeyPath("/escaped"))
# assert result == "This is not interpolated: ${name}"


# def test_multiple_interpolations():
# data = {
# "a": 5,
# "b": 3,
# "inner": {
# "c": 2,
# },
# "result": "${a} + ${b} * ${inner.c} = ${a + b * inner.c}",
# "result_ref": "${when c=${inner.c}, result is ${result}}",
# }
# result = interpolate(data, KeyPath("/result"))
# assert result == "5 + 3 * 2 = 11"
# result_ref = interpolate(data, KeyPath("/result_ref"))
# assert result_ref == "when c=2, result is 5 + 3 * 2 = 11"
# full_result = interpolate(data, KeyPath("/"))
# assert full_result["result"] == result
# assert full_result["result_ref"] == result_ref
# assert full_result["a"] == 5
# assert full_result["b"] == 3
# assert full_result["inner"]["c"] == 2


# def test_interpolation_with_boolean_operations():
# data = {"x": True, "y": False, "result": "${x and y}"}
# result = interpolate(data, KeyPath("/result"))
# assert result is False


# def test_interpolation_with_comparison_operations():
# data = {"a": 10, "b": 5, "result": "${a > b and a < 20}"}
# result = interpolate(data, KeyPath("/result"))
# assert result is True


# def test_interpolation_of_nested_structure():
# data = {
# "outer": {
# "outerval": 10,
# "inner": {"value": 42},
# "message": "The answer is ${inner.value}",
# "message2": "The answer is ${.outerval}",
# }
# }
# result = interpolate(data, KeyPath("/outer"))
# assert isinstance(result, dict)
# assert result["message"] == "The answer is 42"
# assert result["message2"] == "The answer is 10"


# def test_interpolation_in_complex_structure():
# data = {
# "users": [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}],
# "summary": "We have ${len(users)} users. ${users.0.name} is ${users[0].age} years old.",
# }
# result = interpolate(data, KeyPath("/"))
# assert result["summary"] == "We have 2 users. Alice is 30 years old."


##────────────────────────────────────────────────────────────────────────────}}}

from dataclasses import dataclass
from typing import List

test_expr2 = "${@/name\\.greeting..back+2 + / @path.${'haha' + @inner.match }to.list\\[2] } = @haha./../p\\[3{] + ${2+2}"

interp_matches = outermost_interpolation_exprs(test_expr2)


def resolve_keypath(expr: str):
    keypath_matches = find_keypaths(expr)
    if not keypath_matches:
        return expr
    PREPEND = "(__DRACON__PARENT_PATH + __dracon_KeyPath('"
    APPEND = "')).get_obj(__DRACON__CURRENT_ROOT_OBJ)"
    offset = 0
    for match in keypath_matches:
        newexpr = PREPEND + match.expr + APPEND
        expr = expr[: match.start + offset] + newexpr + expr[match.end + offset :]
        original_len = match.end - match.start
        offset += len(newexpr) - original_len
    return expr


def do_safe_eval(expr: str, symbols: dict = {}):
    expr = resolve_keypath(expr)
    print(f'evaluating: {expr}')
    safe_eval = Interpreter(user_symbols=symbols, max_string_length=1000)
    return safe_eval(expr)


def resolve_eval_str(
    expr: str, current_path: str = '/', root_obj: Any = None, allow_recurse: int = 2
) -> Any:
    interpolations = outermost_interpolation_exprs(expr)

    symbols = {
        "__DRACON__CURRENT_PATH": KeyPath(current_path),
        "__DRACON__PARENT_PATH": KeyPath(current_path).parent,
        "__DRACON__CURRENT_ROOT_OBJ": root_obj,
        "__dracon_KeyPath": KeyPath,
    }

    endexpr = None
    if not interpolations:
        return expr

    elif (
        len(interpolations) == 1
        and interpolations[0].start == 0
        and interpolations[0].end == len(expr)
    ):
        endexpr = do_safe_eval(interpolations[0].expr, symbols)

    else:
        offset = 0
        for match in interpolations:  # will be returned as a concatenation of strings
            newexpr = str(
                do_safe_eval(
                    resolve_eval_str(
                        match.expr, current_path, root_obj, allow_recurse=allow_recurse
                    ),
                    symbols,
                )
            )
            expr = expr[: match.start + offset] + newexpr + expr[match.end + offset :]
            original_len = match.end - match.start
            offset += len(newexpr) - original_len
        endexpr = str(expr)

    if allow_recurse != 0 and isinstance(endexpr, str):
        return resolve_eval_str(endexpr, current_path, root_obj, allow_recurse=allow_recurse - 1)

    return endexpr


obj = {
    "name": "John",
    "greetingroot": "Hello, ${@name}!",
    'nested': {
        'inner': {'match': '${2+2}', 'other': 'greetings, ${@/name}!', 'match_ref': '${@/greetingroot}'}
    },
}

KeyPath('/nested.inner/name').get_obj(obj)

resolve_eval_str(obj['nested']['inner']['match'], '/nested.inner.match', obj)
resolve_eval_str(obj['nested']['inner']['other'], '/nested.inner.other', obj)
resolve_eval_str(obj['nested']['inner']['match_ref'], '/nested.inner.match_ref', obj)
# this won't work with a normal dict because there is a change of current path in the reference. 
# It should work with a Dracontainer because accessing the member should trigger resolution
