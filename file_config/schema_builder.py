# Copyright (c) 2018 Stephen Bunn <stephen@bunn.io>
# MIT License <https://opensource.org/licenses/MIT>

import re
import typing
import warnings
import collections
from functools import partial

import attr

from .utils import (
    is_bool_type,
    is_null_type,
    is_array_type,
    is_config_var,
    is_regex_type,
    is_union_type,
    is_config_type,
    is_number_type,
    is_object_type,
    is_string_type,
    is_typing_type,
    is_builtin_type,
    is_integer_type,
    is_compiled_pattern,
)
from .constants import CONFIG_KEY, REGEX_TYPE_NAME


def Regex(pattern):
    return typing.NewType(REGEX_TYPE_NAME, re.compile(pattern))


def _build_attribute_modifiers(
    var, attribute_mapping, ignore=["type", "required", "default"]
):
    if not is_config_var(var):
        raise ValueError(
            f"cannot build field modifiers for {var!r}, is not a config var"
        )

    entry = var.metadata[CONFIG_KEY]
    modifiers = {}

    for (entry_attribute, entry_value) in zip(
        attr.fields(type(entry)), attr.astuple(entry)
    ):
        if entry_value is not None:
            if entry_attribute.name in ignore:
                continue
            elif entry_attribute.name in attribute_mapping:
                # NOTE: required for `isinstance(True, (int, float)) == True`
                if type(entry_value) == entry_attribute.type:
                    modifiers[attribute_mapping[entry_attribute.name]] = entry_value
                else:
                    raise ValueError(
                        f"invalid modifier type for modifier {entry_attribute.name!r} "
                        f"on var {var.name!r}, expected type {entry_attribute.type!r}, "
                        f"received {entry_value!r} of type {type(entry_value)!r}"
                    )
            else:
                warnings.warn(
                    f"field modifier {entry_attribute.name!r} has no effect on var "
                    f"{var.name!r} of type {entry.type!r}"
                )

    return modifiers


def _build_null_type(var, property_path=[]):
    return {"type": "null"}


def _build_bool_type(var, property_path=[]):
    return {"type": "boolean"}


def _build_string_type(var, property_path=[]):
    schema = {"type": "string"}
    if is_builtin_type(var):
        return schema

    schema.update(
        _build_attribute_modifiers(var, {"min": "minLength", "max": "maxLength"})
    )

    if is_regex_type(var.type):
        schema["pattern"] = var.type.__supertype__.pattern
    return schema


def _build_integer_type(var, property_path=[]):
    schema = {"type": "integer"}
    if is_builtin_type(var):
        return schema

    schema.update(_build_attribute_modifiers(var, {"min": "minimum", "max": "maximum"}))
    return schema


def _build_number_type(var, property_path=[]):
    schema = {"type": "number"}
    if is_builtin_type(var):
        return schema

    schema.update(_build_attribute_modifiers(var, {"min": "minimum", "max": "maximum"}))
    return schema


def _build_array_type(var, property_path=[]):
    schema = {"type": "array", "items": {"$id": f"#/{'/'.join(property_path)}/items"}}
    if is_builtin_type(var):
        return schema

    schema.update(
        _build_attribute_modifiers(
            var,
            {
                "min": "minItems",
                "max": "maxItems",
                "unique": "uniqueItems",
                "contains": "contains",
            },
        )
    )

    if is_typing_type(var.type) and len(var.type.__args__) > 0:
        # NOTE: typing.List only allows one typing argument
        nested_type = var.type.__args__[0]
        schema["items"].update(
            _build(nested_type, property_path=property_path + ["items"])
        )
    return schema


def _build_object_type(var, property_path=[]):
    schema = {"type": "object"}
    if is_builtin_type(var):
        return schema

    entry = var.metadata[CONFIG_KEY]

    if isinstance(entry.min, int):
        schema["minProperties"] = entry.min
    if isinstance(entry.max, int):
        schema["maxProperties"] = entry.max

    # NOTE: typing.Dict only accepts two typing arguments
    if is_typing_type(var.type) and len(var.type.__args__) == 2:
        (key_type, value_type) = var.type.__args__

        key_pattern = "^(.*)$"
        if hasattr(key_type, "__supertype__") and is_compiled_pattern(
            key_type.__supertype__
        ):
            key_pattern = key_type.__supertype__.pattern
        elif not is_string_type(key_type):
            raise ValueError(
                f"cannot serialize object with key of type {key_type!r}, "
                f"located in var {var.name!r}"
            )

        schema["patternProperties"] = {
            key_pattern: _build(value_type, property_path=property_path)
        }

    return schema


def _build_type(type_, value, property_path=[]):
    for (type_check, builder) in (
        (is_null_type, _build_null_type),
        (is_bool_type, _build_bool_type),
        (is_string_type, _build_string_type),
        (is_integer_type, _build_integer_type),
        (is_number_type, _build_number_type),
        (is_array_type, _build_array_type),
        (is_object_type, _build_object_type),
    ):
        if type_check(type_):
            return builder(value, property_path=property_path)

    warnings.warn(f"unhandled translation for type {type_!r}")
    return {}


def _build_var(var, property_path=[]):
    if not is_config_var(var):
        raise ValueError(f"var {var!r} is not a config var")

    schema = {"$id": f"#/{'/'.join(property_path)}/{var.name}"}
    entry = var.metadata[CONFIG_KEY]

    if var.default is not None:
        schema["default"] = var.default

    if entry is not None:
        if isinstance(entry.title, str):
            schema["title"] = entry.title
        if isinstance(entry.description, str):
            schema["description"] = entry.description
        if isinstance(entry.examples, collections.Iterable) and len(entry.examples) > 0:
            schema["examples"] = entry.examples

    # handle typing.Union types by simply using the "anyOf" key
    if is_union_type(var.type):
        type_union = {"anyOf": []}
        for allowed_type in var.type.__args__:
            type_union["anyOf"].append(
                _build_type(
                    allowed_type, allowed_type, property_path=property_path + [var.name]
                )
            )
        schema.update(type_union)
    else:
        schema.update(
            _build_type(var.type, var, property_path=property_path + [var.name])
        )
    return schema


def _build_config(config_cls, property_path=[]):
    if not is_config_type(config_cls):
        raise ValueError(f"class {config_cls!r} is not a config class")

    schema = {"type": "object", "required": [], "properties": {}}
    cls_entry = getattr(config_cls, CONFIG_KEY)

    # add schema title, defaults to config classes `__qualname__`
    schema_title = cls_entry.get("title", config_cls.__qualname__)
    if isinstance(schema_title, str):
        schema["title"] = schema_title

    schema_description = cls_entry.get("description")
    if isinstance(schema_description, str):
        schema["description"] = schema_description

    # if the length of the property path is 0, assume that current object is root
    if len(property_path) <= 0:
        schema["$id"] = f"{config_cls.__qualname__}.json"
        schema["$schema"] = "http://json-schema.org/draft-07/schema#"
    else:
        schema["$id"] = f"#/{'/'.join(property_path)}"

    property_path.append("properties")
    for var in attr.fields(config_cls):
        if not is_config_var(var):
            # encountered attribute is not a serialized field (i.e. missing CONFIG_KEY)
            continue
        entry = var.metadata[CONFIG_KEY]
        if entry.required:
            schema["required"].append(var.name)

        if is_config_type(var.type):
            schema["properties"][var.name] = _build_config(
                var.type, property_path=property_path + [var.name]
            )
        else:
            schema["properties"][var.name] = _build_var(
                var, property_path=property_path
            )

    return schema


def _build(value, property_path=[]):
    if is_config_type(value):
        return _build_config(value, property_path=property_path)
    elif is_config_var(value):
        return _build_var(value, property_path=property_path)
    elif is_builtin_type(value):
        return _build_type(value, value, property_path=property_path)
    return _build_type(type(value), value, property_path=property_path)


def build_schema(config_cls):
    return _build_config(config_cls, property_path=[])