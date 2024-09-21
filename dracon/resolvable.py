from typing import (
    Any,
    TypeVar,
    Generic,
    Type,
    Optional,
    Callable,
    List,
)

from dracon.composer import (
    CompositionResult,
    KeyPath,
    ROOTPATH,
    escape_keypath_part,
)

from dracon.nodes import (
    make_node,
    IncludeNode,
    MergeNode,
    DraconMappingNode,
)

from pydantic import BaseModel
from pydantic_core import core_schema
from dracon.utils import get_inner_type, node_print
from dracon.merge import MergeKey
from copy import deepcopy

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

    def resolve(self, context=None, localns=None, interpolate_all=None):
        """
        Resolve the object from the stored node and constructor, adding context and localns if needed
        Note: it doesn't necessarily returns an object of inner_type. In theory yes,
        but in practice, the node tag could have been changed at any point. And a resolvable doesn't
        enforce any constraints on the type of the object it will return. It just pauses the construction
        and allows you to resume it later.
        """
        assert self.ctor is not None
        assert self.node is not None
        ctor = deepcopy(self.ctor)
        ctor.context.update(context or {})
        ctor.localns.update(localns or {})
        if interpolate_all is not None:
            ctor.interpolate_all = interpolate_all
        return ctor.construct_object(self.node)

    def copy(self):
        return deepcopy(self)

    def empty(self):
        return self.node is None or not self.node.value

    def __bool__(self):
        return not self.empty()

    def merge_node(self, node, merge_key: str = '<<{+>}'):
        """
        Merge a node with the current node.
        """
        assert self.ctor is not None
        loader = self.ctor.drloader

        self.node = self.node or make_node({})
        res = CompositionResult(root=self.node)
        assert isinstance(res.root, DraconMappingNode)

        res.root[MergeNode(merge_key)] = node

        # res.merge_nodes.extend([ROOTPATH + p for p in res.root.get_merge_nodes()])
        # res.include_nodes.extend([ROOTPATH + p for p in res.root.get_include_nodes()])
        res.special_nodes['merge'].extend([ROOTPATH + p for p in res.root.get_merge_nodes()])
        res.special_nodes['include'].extend([ROOTPATH + p for p in res.root.get_include_nodes()])

        new_resolvable = Resolvable(
            node=loader.post_process_composed(res).root,
            ctor=self.ctor,
            inner_type=self.inner_type,  # type: ignore
        )

        return new_resolvable

    def merge_with(self, other: 'Resolvable', merge_key: str = '<<{+>}'):
        return self.merge_node(other.node, merge_key)

    def merge_attrs(self, attr: str, subattrs: List[str], merge_key: str = '<<{+>}'):
        """
        Merge some attributes of the object into another attribute.
        For example, say we have a class MyClass with attributes attr1, attr2, subattr_1, subattr_2
        If we want attr1 to contain subattr_1 and subattr_2, we can do this with this method like so:
        new_resolvable = resolvable_obj.merge_attrs('attr1', ['subattr_1', 'subattr_2'])
        """
        to_merge = make_node({attr: {subattr: IncludeNode(f'/{subattr}') for subattr in subattrs}})
        return self.merge_node(to_merge, merge_key)
