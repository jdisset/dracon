# Dracon
 
Dracon is a simple modular configuration system built around sensible and natural-feeling YAML extensions.

## Features

- Nested inclusion of external configuration files
- Flexible and powerful merging strategies
- Future support for serialization and deserialization of objects using !type[...] tags
- Future support for native variable interpolation and substitution using ${...} syntax
 
# Syntax Overview

The enhanced merge notation allows for flexible and powerful merging strategies, with options for specifying list and dictionary merge behaviors, depth limits, and priority settings.

## Merge Operators

 1. **Vanilla Merge (`<<:`)**
	 - Default YAML merge, where the values from the introduced dictionary are merged into the existing dictionary, and existing dictionary keys take precedence in case of conflicts.
	 - Equivalent to `<<{~>}[~>]:`

 2. **Enhanced Merge (`<<[options]{options}`)**
	 - Augment the YAML merge syntax with additional merging preference options using a well-defined list of symbols:
		- **List Merge Options:**
		  - `+`: Extend lists and/or dictionaries recursively (unless depth modifier is specified, in which case it will extend until that depth and then replace).
		  - `~`: Replace dictionaries or lists entirely.
		- **Priority Options:**
		  - `<`: Introduced dictionary takes precedence.
		  - `>`: Existing dictionary takes precedence.
		- **Depth Limit:**
		  - `+N`: Merge dictionaries up to `N` depth levels.
		- **Repeating Merge:**
		  - `*`: Repeat merge for each item in a list/dict and define the `${!index}`, `${!key}`, and `${!value}` variables for the scope.

		  
		  
### Operator Examples

```yaml
existing:
	<<{+<}[+<]: *introduced
```
-> Merge the introduced dictionary into the existing dictionary in append mode for both lists and dictionaries.
	* If a key exists in both dictionaries:
		- If the key is a list in both dictionaries, extend the list (introduced will appear first, because of `[<]`).
		- If the key is a dictionary in both dictionaries, recurse 
		- If the key is a scalar in both dictionaries, the introduced value takes precedence (because of `{<}`).
	* Keys unique to either dictionary are added.
	
```yaml
existing:
	<<{~<}[~>]: *introduced
```
-> Merge the introduced dictionary into the existing dictionary in shallow replace mode for dictionaries and lists.
	* If a key exists in both dictionaries:
		- If the key is a list in both dictionaries, replace with the existing list (replace because of `[~]`, existing has priority because of `[>]`).
		- Regardless if the key is a dictionary or a scalar in both dictionaries, replace with the introduced value, without recursion (because of `{~}`).
	* Keys unique to either dictionary are added.

```yaml
existing:
	<<{+2<}: *introduced
```
* Merge using the `{+<}` strategy up to 2 levels deep.
* After 2 levels, switch to merging using the `{~<}` strategy.
		  
		  
### Combining Merge Options

 You can combine any dict arguments by putting all of them inside `{}`. For example:

 - `{+<1}`: Merge dictionaries up to one depth level, extend lists, and the introduced dictionary takes precedence.
 - `{<+}`: The introduced dictionary takes precedence, and lists are extended.
 - `{~>}`: Replace existing keys entirely, and the existing dictionary takes precedence.

## Inclusion Syntax

Dracon supports inclusion of external configuration files in the YAML configuration files. 
It uses the traditional YAML alias syntax to include external files, with the addition of a prefix to specify the type of inclusion.
The include paths can be specified in the following formats:

- `pkg:pkg_name:config_path[@keypath]`
- `file:config_path[@keypath]`
 
`@keypath` is optional and is used to specify a subpath within the included dictionary, i.e. path.to.list.1 = obj['path']['to']['list'][1].
a configuration path can be specified with or without the .yaml extension.

### Inclusion Examples

```yaml

# Include a file from the filesystem
included: *file:./config.yaml
included_abs: *file:/path/to/config.yaml

# Include a file from a package
included_pkg: *pkg:pkg_name:config.yaml

<<: *pkg:pkg_name:config.yaml # merge include at the root

obj:
 key: *file:./
 <<{+<}[+<]: *file:./config.yaml # 
 <<: *pkg:pkg_name:config.yaml

```

