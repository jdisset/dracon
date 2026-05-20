# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
"""Sibling `!each` keys with the same iterable expression are distinct.

`!each(var) ${expr}` is a directive: the `(var)` is part of the key from
the user's point of view. The composer's duplicate-key check used to dedup
on `key.value` alone, so two `!each` keys with identical iterable strings
collided even when they bound different variables.
"""
from dracon import loads


def test_two_each_keys_same_iterable_different_var():
    out = loads("""
        items:
          !each(i) ${range(2)}:
            - "a_${i}"
          !each(j) ${range(2)}:
            - "b_${j}"
    """)
    assert list(out["items"]) == ["a_0", "a_1", "b_0", "b_1"]


def test_three_each_keys_same_iterable():
    out = loads("""
        items:
          !each(i) ${range(2)}:
            - "x_${i}"
          !each(j) ${range(2)}:
            - "y_${j}"
          !each(k) ${range(2)}:
            - "z_${k}"
    """)
    assert list(out["items"]) == ["x_0", "x_1", "y_0", "y_1", "z_0", "z_1"]


def test_two_if_directives_with_same_condition():
    """Same defensive guarantee for !if: textually-identical conditions
    in sibling !if blocks must not collide."""
    out = loads("""
        result:
          !if ${True}:
            then:
              a: 1
          !if ${True}:
            then:
              b: 2
    """)
    assert dict(out["result"]) == {"a": 1, "b": 2}
