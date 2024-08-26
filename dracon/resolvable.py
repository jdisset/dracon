from typing import (
    Any,
    Dict,
    Callable,
    Optional,
    Tuple,
    List,
    TypeVar,
    Generic,
    ForwardRef,
    Annotated,
    Type,
    get_args,
)
from pydantic import TypeAdapter, BaseModel, field_validator, ConfigDict, WrapValidator, Field, ValidationError
from pydantic_core import core_schema
from copy import copy

T = TypeVar("T")

class Resolvable(Generic[T]):
    # ony useful to force dumping as a lazy object
    # and act as a a transparent wrapper that can be used as type hint

    def __init__(self, node: Optional[Any] = None, ctor: Optional[Any] = None, inner_type: Optional[Type[T]] = None):
        self.node = node
        self.ctor = ctor
        if inner_type is not None:
            self.inner_type = inner_type
        else:
            self.inner_type = get_inner_type(self.__class__)

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: Any
    ) -> core_schema.CoreSchema:
        cls_type = get_inner_type(cls)
        t_schema = handler(cls_type)
        return core_schema.union_schema([
            t_schema,
            core_schema.is_instance_schema(cls),
        ])


    def resolve(self, context=None, localns=None):
        assert self.ctor is not None
        assert self.node is not None
        self.ctor.context.update(context or {})
        self.ctor.localns.update(localns or {})
        return self.ctor.construct_object(self.node)


def get_inner_type(resolvable_type: Type[Resolvable]):
    args = get_args(resolvable_type)
    if args:
        return args[0]
    return Any

