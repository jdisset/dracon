## {{{                          --     imports     --
import re
import pytest
from dracon import dump, loads
from dracon.loader import DraconLoader
from dracon.deferred import DeferredNode, make_deferred
from dracon.dracontainer import Dracontainer, Mapping, Sequence, resolve_all_lazy
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
import concurrent.futures
import threading
from dracon.interpolation import outermost_interpolation_exprs
from dracon.lazy import LazyInterpolable

from pydantic.dataclasses import dataclass
from dracon.keypath import KeyPath
from typing import Any, Dict, Callable, Optional, Tuple, List
import copy
from dracon.interpolation_utils import find_field_references
from asteval import Interpreter

import pickle
import multiprocessing
import concurrent.futures
import operator

##────────────────────────────────────────────────────────────────────────────}}}


# Session-scoped pool fixture
@pytest.fixture(scope="session")
def process_pool():
    """Create a process pool that's reused across tests"""
    pool = multiprocessing.Pool(processes=3)
    yield pool
    pool.close()
    pool.join()


class ClassA(BaseModel):
    index: int
    name: str = ''

    @property
    def name_index(self):
        return f"{self.index}: {self.name}"


def get_index(obj):
    return obj.index


def test_deferred():
    yaml_content = """
    !define i42 : !int 42

    a_obj: !ClassA
        index: &aid ${i42}
        name: oldname
        <<{<+}: 
            name: "new_name ${&aid}"

    nested: !deferred
        !define aid: ${get_index(construct(&/a_obj))}
        a_index: ${aid}
        aname: ${&/a_obj.name}
        constructed_nameindex: ${construct(&/a_obj).name_index}

    """

    loader = DraconLoader(enable_interpolation=True, context={'ClassA': ClassA})
    loader.yaml.representer.full_module_path = False
    loader.context['get_index'] = get_index
    config = loader.loads(yaml_content)
    config.resolve_all_lazy()

    assert isinstance(config.a_obj, ClassA)
    assert config['a_obj'].index == 42
    assert config['a_obj'].name == "new_name 42"

    assert type(config['nested']) is DeferredNode

    nested_comp = config.nested.compose()
    nested = config.nested.construct()

    assert nested.a_index == 42
    assert nested.aname == "new_name 42"
    assert nested.constructed_nameindex == "42: new_name 42"


def test_deferred_explicit():
    yaml_content = """
    !define i42 : !int 42

    a_obj: !ClassA &ao
        index: &aid ${i42}
        name: oldname
        <<{<+}: 
            name: "new_name ${&aid}"


    b_obj: !deferred:ClassA &bo
        index: &bid ${int(i42) - 10}
        name: oldname
        <<{<+}: 
            name: "new_name ${&bid}"

    nested:
        !define aid: ${get_index(construct(&/a_obj)) + $CONSTANT}
        a_index: ${aid}
        aname: ${&/a_obj.name}
        constructed_nameindex: ${construct(&/a_obj).name_index}
        !define ao: ${&/a_obj}
        !define bo: ${&/b_obj} # required to go through a reference when pointing to a deferred node
        obj2:
            <<: !include ao
        obj3: !include $ao
        obj4: !include $bo
            

    """

    loader = DraconLoader(
        enable_interpolation=True, context={'ClassA': ClassA}, deferred_paths=['/nested']
    )
    loader.yaml.representer.full_module_path = False
    config = loader.loads(yaml_content)
    resolve_all_lazy(config)

    assert isinstance(config.a_obj, ClassA)
    assert config['a_obj'].index == 42
    assert config['a_obj'].name == "new_name 42"

    assert type(config['nested']) is DeferredNode

    config.nested.update_context({'get_index': get_index, '$CONSTANT': 10})
    nested = config.nested.construct()
    resolve_all_lazy(nested)

    assert nested.a_index == 52
    assert nested.aname == "new_name 42"
    assert nested.constructed_nameindex == "42: new_name 42"

    assert isinstance(config.b_obj, DeferredNode)
    b_obj = config.b_obj.construct()
    resolve_all_lazy(b_obj)
    assert isinstance(b_obj, ClassA)
    assert b_obj.index == 32
    assert b_obj.name == "new_name 32"

    print(f"{config.a_obj=}, {nested.obj2=}")
    # here, nested.obj2 is a mapping... it should be a ClassA instance

    assert nested.obj2 == config.a_obj
    assert nested.obj3 == config.a_obj
    assert isinstance(nested.obj4, DeferredNode)
    assert nested.obj4.construct() == b_obj


def process_deferred_node(node_data: Dict[str, Any]) -> Any:
    """Helper function for multiprocessing tests"""
    pickled_node, context = node_data
    node = pickle.loads(pickled_node)
    if context:
        node.update_context(context)
    return node.construct()


def test_deferred_node_pickling():
    """Test pickling and unpickling of DeferredNode"""
    yaml_content = """
    !define i42 : !int 42

    nested: !deferred
        !define aid: ${get_index(construct(&/a_obj))}
        a_index: ${aid}
        aname: ${&/a_obj.name}
        constructed_nameindex: ${construct(&/a_obj).name_index}

    a_obj: !ClassA
        index: &aid ${i42}
        name: oldname
        <<{<+}: 
            name: "new_name ${&aid}"
    """

    loader = DraconLoader(enable_interpolation=True, context={'ClassA': ClassA})
    loader.context['get_index'] = get_index
    config = loader.loads(yaml_content)

    # Pickle the entire config
    pickled_config = pickle.dumps(config)
    unpickled_config = pickle.loads(pickled_config)

    # Verify the deferred node behavior is preserved
    unpickled_config.resolve_all_lazy()
    nested = unpickled_config.nested.construct()

    assert nested.a_index == 42
    assert nested.aname == "new_name 42"
    assert nested.constructed_nameindex == "42: new_name 42"


def doublex(x):
    return x * 2


def double(x: int) -> int:
    return x * 2


def add_ten(x: int) -> int:
    return x + 10


def square(x: int) -> int:
    return x**2


def test_deferred_node_context_pickling():
    """Test pickling DeferredNode with context updates"""
    yaml_content = """
    nested: !deferred
        value: ${VALUE}
        computed: ${COMPUTE(10)}
    """

    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)

    # Pickle the node
    pickled_node = pickle.dumps(config.nested)
    unpickled_node = pickle.loads(pickled_node)

    # Update context after unpickling
    context = {'VALUE': 42, 'COMPUTE': doublex}
    unpickled_node.update_context(context)

    result = unpickled_node.construct()
    assert result.value == 42
    assert result.computed == 20


def test_parallel_deferred_node_processing(process_pool):
    """Test processing multiple deferred nodes in parallel"""
    yaml_content = """
    nodes:
        node1: !deferred
            value: ${VALUE + 1}
        node2: !deferred
            value: ${VALUE + 2}
        node3: !deferred
            value: ${VALUE + 3}
    """

    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)

    nodes = [
        (pickle.dumps(config.nodes.node1), {'VALUE': 10}),
        (pickle.dumps(config.nodes.node2), {'VALUE': 20}),
        (pickle.dumps(config.nodes.node3), {'VALUE': 30}),
    ]

    results = process_pool.map(process_deferred_node, nodes)

    assert [r.value for r in results] == [11, 22, 33]


def construct_deferred(node: DeferredNode) -> Any:
    print(f"Constructing {node}")
    print(f"{node.context=}")
    return node.construct()


def test_parallel_deferred_nodes(process_pool):
    """Test processing multiple deferred nodes in parallel"""
    yaml_content = """
    nodes:
        !each(val) ${VALUES}:
            - !deferred
              value: ${val + 1}
              ainst: !ClassA
                index: ${int(val) + 1}
                name: "Item ${int(val) + 1}"
    """

    loader = DraconLoader(
        enable_interpolation=True,
        context={
            'VALUES': [10, 20, 30],
            'ClassA': ClassA,
        },
    )
    config = loader.loads(yaml_content)

    nodes = config.nodes
    print(f"{nodes=}")

    assert len(nodes) == 3

    results = process_pool.map(construct_deferred, nodes)

    assert [r.value for r in results] == [11, 21, 31]
    assert all(isinstance(r.ainst, ClassA) for r in results)


def test_complex_deferred_node_pickling():
    """Test pickling complex deferred nodes with cross-references"""
    yaml_content = """
    !define i42 : !int 42

    a_obj: !ClassA &ao
        index: &aid ${i42}
        name: oldname
        <<{<+}: 
            name: "new_name ${&aid}"

    b_obj: !deferred:ClassA &bo
        index: &bid ${int(i42) - 10}
        name: oldname
        <<{<+}: 
            name: "new_name ${&bid}"

    nested:
        !define aid: ${get_index(construct(&/a_obj)) + $CONSTANT}
        a_index: ${aid}
        aname: ${&/a_obj.name}
        constructed_nameindex: ${construct(&/a_obj).name_index}
        !define ao: ${&/a_obj}
        !define bo: ${&/b_obj}
        obj2: !include ao
        obj3: !include $ao
        obj4: !include $bo
    """

    loader = DraconLoader(
        enable_interpolation=True, context={'ClassA': ClassA}, deferred_paths=['/nested']
    )
    config = loader.loads(yaml_content)

    # Pickle entire config
    pickled_config = pickle.dumps(config)
    unpickled_config = pickle.loads(pickled_config)

    # Update context and resolve
    unpickled_config.nested.update_context({'get_index': get_index, '$CONSTANT': 10})

    nested = unpickled_config.nested.construct()
    resolve_all_lazy(nested)

    assert nested.a_index == 52
    assert nested.aname == "new_name 42"
    assert nested.constructed_nameindex == "42: new_name 42"

    b_obj = unpickled_config.b_obj.construct()
    resolve_all_lazy(b_obj)
    assert isinstance(b_obj, ClassA)
    assert b_obj.index == 32
    assert b_obj.name == "new_name 32"


def test_parallel_deferred_class_instantiation(process_pool):
    """Test parallel instantiation of deferred class objects"""
    yaml_content = """
    listitems:
        obj1: !deferred:ClassA
            index: ${BASE + 1}
            name: "Item ${BASE + 1}"
        obj2: !deferred:ClassA
            index: ${BASE + 2}
            name: "Item ${BASE + 2}"
        obj3: !deferred:ClassA
            index: ${BASE + 3}
            name: "Item ${BASE + 3}"
    """

    loader = DraconLoader(enable_interpolation=True, context={'ClassA': ClassA})
    config = loader.loads(yaml_content)

    # Prepare nodes for parallel processing
    nodes = [
        (pickle.dumps(node), {'BASE': i * 10})
        for i, node in enumerate(
            [config.listitems.obj1, config.listitems.obj2, config.listitems.obj3]
        )
    ]

    results = process_pool.map(process_deferred_node, nodes)

    for i, result in enumerate(results):
        assert isinstance(result, ClassA)
        base = i * 10
        assert result.index == base + (i + 1)
        assert result.name == f"Item {base + (i + 1)}"


def test_deferred_node_thread_safety():
    """Test thread-safe processing of deferred nodes"""
    yaml_content = """
    node: !deferred
        counter: ${COUNTER}
        value: ${VALUE}
    """

    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)

    # Use threading.Lock for thread-safe counter increment
    counter_lock = threading.Lock()
    counter = 0

    def process_node(value):
        nonlocal counter
        with counter_lock:
            counter += 1
            current_counter = counter

        node = pickle.loads(pickle.dumps(config.node))
        node.update_context({'COUNTER': current_counter, 'VALUE': value})
        return node.construct()

    # Process in multiple threads
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(process_node, i) for i in range(10)]
        results = [f.result() for f in futures]

    # Verify results
    counters = set(r.counter for r in results)
    assert len(counters) == 10, f"Expected 10 unique counters, got {len(counters)}: {counters}"
    assert min(counters) == 1
    assert max(counters) == 10
    assert sorted(r.value for r in results) == list(range(10))


def process_counter_node(args: Tuple[int, int]) -> Any:
    """Process a node with counter and value"""
    value, counter = args
    yaml_content = """
    node: !deferred
        counter: ${COUNTER}
        value: ${VALUE}
    """
    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)
    node = config.node
    node.update_context({'COUNTER': counter, 'VALUE': value})
    return node.construct()


def test_deferred_node_process_safety(process_pool):
    """Test process-safe processing of deferred nodes using a shared counter"""
    # Process in multiple processes with pre-assigned counters
    args = [(i, i + 1) for i in range(10)]  # (value, counter)
    results = process_pool.map(process_counter_node, args)

    # Verify results
    counters = set(r.counter for r in results)
    assert len(counters) == 10, f"Expected 10 unique counters, got {len(counters)}: {counters}"
    assert min(counters) == 1
    assert max(counters) == 10
    assert sorted(r.value for r in results) == list(range(10))


def test_process_pool_reuse(process_pool):
    """Test reusing process pool for multiple deferred node operations"""
    yaml_content = """
    node: !deferred
        operation_name: ${OPERATION_NAME}
        input: ${INPUT}
        result: ${OPERATION(INPUT)}
    """

    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)

    # Use named functions instead of lambdas
    operations = [(double, "double"), (add_ten, "add_ten"), (square, "square")]

    def create_node_data(op_func, op_name, input_value):
        return (
            pickle.dumps(config.node),
            {'OPERATION': op_func, 'INPUT': input_value, 'OPERATION_NAME': op_name},
        )

    # First batch
    nodes_data = [create_node_data(op_func, op_name, 5) for op_func, op_name in operations]
    results1 = process_pool.map(process_deferred_node, nodes_data)

    # Second batch with different input
    nodes_data = [create_node_data(op_func, op_name, 10) for op_func, op_name in operations]
    results2 = process_pool.map(process_deferred_node, nodes_data)

    # Verify first batch
    assert results1[0].result == 10  # 5 * 2
    assert results1[1].result == 15  # 5 + 10
    assert results1[2].result == 25  # 5 ** 2

    # Verify second batch
    assert results2[0].result == 20  # 10 * 2
    assert results2[1].result == 20  # 10 + 10
    assert results2[2].result == 100  # 10 ** 2


def unpack_call(func, args):
    return func(*args)


def test_complex_operations(process_pool):
    """Test processing deferred nodes with more complex operations"""
    yaml_content = """
    node: !deferred
        input: ${INPUT}
        operation: ${OPERATION_NAME}
        args: ${ARGS}
        result: ${unpack_call(OPERATION, ARGS)}
    """

    loader = DraconLoader(enable_interpolation=True, context={'unpack_call': unpack_call})
    config = loader.loads(yaml_content)

    # Test data using built-in functions and operators
    test_cases = [
        (operator.add, "add", (5, 3)),
        (operator.mul, "multiply", (4, 6)),
        (operator.truediv, "divide", (10, 2)),
        (max, "max", (7, 12, 3)),
        (min, "min", (8, 2, 5)),
    ]

    def create_node_data(op_func, op_name, args):
        return (
            pickle.dumps(config.node),
            {
                'OPERATION': op_func,
                'OPERATION_NAME': op_name,
                'ARGS': args,
                'INPUT': args[0],  # First arg as input for reference
            },
        )

    nodes_data = [create_node_data(op_func, op_name, args) for op_func, op_name, args in test_cases]
    results = process_pool.map(process_deferred_node, nodes_data)

    # Verify results
    assert results[0].result == 8  # 5 + 3
    assert results[1].result == 24  # 4 * 6
    assert results[2].result == 5.0  # 10 / 2
    assert results[3].result == 12  # max(7, 12, 3)
    assert results[4].result == 2  # min(8, 2, 5)


def test_builtin_operations(process_pool):
    """Test processing deferred nodes with built-in operations"""
    yaml_content = """
    node: !deferred
        input: ${INPUT}
        processed: ${PROCESS(INPUT)}
        constant: constant
    """

    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)

    # Use built-in functions that are always picklable
    processors = [
        (abs, "abs", -5),
        (str.upper, "upper", "hello"),
        (len, "len", [1, 2, 3]),
        (sorted, "sorted", [3, 1, 4, 1, 5]),
        (bool, "bool", 1),
    ]

    def create_node_data(proc_func, proc_name, test_input):
        return (pickle.dumps(config.node), {'PROCESS': proc_func, 'INPUT': test_input})

    nodes_data = [
        create_node_data(proc_func, proc_name, test_input)
        for proc_func, proc_name, test_input in processors
    ]
    results = process_pool.map(process_deferred_node, nodes_data)

    # Verify results
    assert results[0].processed == 5  # abs(-5)
    assert results[1].processed == "HELLO"  # "hello".upper()
    assert results[2].processed == 3  # len([1, 2, 3])
    assert results[3].processed == [1, 1, 3, 4, 5]  # sorted([3, 1, 4, 1, 5])
    assert results[4].processed == True  # bool(1)def test_large_parallel_processing():

    assert all(r.constant == "constant" for r in results)


def test_large_parallel_processing(process_pool):
    """Test processing a large number of deferred nodes in parallel"""
    yaml_content = """
    node: !deferred
        input: ${INPUT}
        result: ${INPUT * 2}
        batch: ${BATCH}
        classAinst: !ClassA
            index: ${INPUT}
            name: "Item ${INPUT}"
    """

    loader = DraconLoader(enable_interpolation=True, context={'ClassA': ClassA})
    config = loader.loads(yaml_content)

    # Create a large number of nodes
    num_nodes = 100
    batch_size = 10
    nodes_data = []

    for batch in range(num_nodes // batch_size):
        for i in range(batch_size):
            value = batch * batch_size + i
            nodes_data.append((pickle.dumps(config.node), {'INPUT': value, 'BATCH': batch}))

    results = process_pool.map(process_deferred_node, nodes_data, chunksize=10)

    # Verify results
    for i, result in enumerate(results):
        assert result.input == i
        assert result.result == i * 2
        assert result.batch == i // batch_size
        assert isinstance(result.classAinst, ClassA)
        assert result.classAinst.index == i
        assert result.classAinst.name == f"Item {i}"

def test_make_deferred():

    inode = make_deferred(42)
    assert inode.construct() == 42

    snode = make_deferred("hello")
    assert snode.construct() == "hello"






