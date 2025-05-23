# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

from typing import (
    Any,
    TypeVar,
    Generic,
    Type,
    Optional,
    List,
)

from pydantic_core import core_schema
from dracon.utils import get_inner_type, deepcopy


T = TypeVar("T")

"""
> # Resolvable objects
> A Resolvable stores the actual yaml node + the constructor that can be used to resume construction.

It's essentially a snapshot of the construction process.
It's useful when you want to 
 -> manually orchestrate the construction of some objects in a specific order (e.g. you need to parse some args first)
 -> add some context to the construction (for example, $SOME_VAR) that is not available at the time of parsing
 -> merge 2 or more yaml nodes manually (the dracon merge operator works on nodes or dicts, not general objects)

>[!WARNING] Resolvable != Interpolable
> `Resolvable` could understandably be confused with a `(Lazy)Interpolable`. They are different concepts:
>  -> The `(Lazy)Interpolable` class is used to store and defer the __interpolation__ of an interpolable __value__ e.g. `${2 + 2}`
>  -> The `Resolvable` class is used to pause and defer the __construction__ of a __whole branch__ until asked to resume (resolve)
> A resolvable can contain Interpolable leaves, and can even contain other Resolvables. 

"""


class Resolvable(Generic[T]):
    def __init__(
        self,
        node: Optional[Any] = None,
        ctor: Optional[Any] = None,
        inner_type: Optional[Type[T]] = None,
    ):
        self.node = node
        self.ctor = ctor
        if inner_type is not None:
            self.inner_type = inner_type
        else:
            self.inner_type = get_inner_type(self.__class__)

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> core_schema.CoreSchema:
        cls_type = get_inner_type(cls)
        t_schema = handler(cls_type)
        return core_schema.union_schema(
            [
                t_schema,
                core_schema.is_instance_schema(cls),
            ]
        )

    def resolve(self, context=None):
        """
        Resolve the object from the stored node and constructor, adding context if needed
        Note: it doesn't necessarily returns an object of inner_type. In theory yes,
        but in practice, the node tag could have been changed at any point. And a resolvable doesn't
        enforce any constraints on the type of the object it will return. It just pauses the construction
        and allows you to resume it later.
        """
        assert self.ctor is not None
        assert self.node is not None
        ctor = deepcopy(self.ctor)
        ctor.dracon_loader.context.update(context or {})
        return ctor.construct_object(self.node)

    def copy(self):
        return deepcopy(self)

    def empty(self):
        return self.node is None or not self.node.value

    def __bool__(self):
        return not self.empty()

    def __repr__(self):
        return f"Resolvable(node={self.node}, inner_type={self.inner_type})"
