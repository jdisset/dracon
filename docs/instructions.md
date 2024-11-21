# Summary of instruction Nodes and special tags

Dracon can parse special instruction nodes that help manipulate the configuration object.
Instructions are tags that start with `!`.

## !define varname: value

The `!define` (and `!set_default`) instructions allow you to define variables in your configuration file.

```yaml
!define var1: 42
!set_default var2: 3.14 # only set if not already defined

# Use the defined variables
value1: ${var1}
value2: ${var2}
```

## !if

The `!if` instruction allows you to conditionally include or exclude parts of your configuration.

```yaml
!define condition: true

!if: ${condition}
  key: value
```

## !each(varname): iterable

The `!each` instruction allows you to iterate over a list or dictionary and include or exclude parts of your configuration.

```yaml
!each(item): [1, 2, 3]
  item_${item}: ${item}
```

## !noconstruct

The `!noconstruct` instruction prevents the construction of the current node.

example:

```yaml
!noconstruct key: value # won't appear in the final configuration
other_key: ${&/key} # OK (it's a copy of the /key node), will be correctly replaced by "value" on evaluation
```

The final configuration will be `{other_key: value}`.

> [!Note]
> You can also use any top-level mapping node with a key that starts with `__dracon__`:
> just as if it had a `!noconstruct` tag, it won't appear in the final configuration.

## !include path

See [File Inclusion](includes.md)

## !MyType, !package.MyType

That's the general syntax for specifying that a node should be constructed as an instance of a specific class. You can register any class in the `DraconLoader` instance within the context dictionary. If a package (or module) is specified, Dracon will try to import it and use the class from there.

By default, Dracon will try to use a Pydantic model if available to validata and construct the node.

```yaml
!Person
name: Alice
age: 42
```

```python
from dracon import DraconLoader
from pydantic import BaseModel

class Person(BaseModel):
    name: str
    age: int

loader = DraconLoader(context={'Person': Person})
person = loader.load('person.yaml')

assert isinstance(person, Person)
assert person.name == 'Alice'
assert person.age == 42
```
