#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""
A tiny JSON Schema (draft 2020-12) validator, standard library only.

It covers just the keywords the kit's schemas use: type, required, properties,
items, enum, pattern, additionalProperties, and local $ref ("#/$defs/<name>").
Any other keyword is ignored, so keep the schemas to this list.

Usage: python3 installer/schema_check.py SCHEMA.json DOC.json [DOC.json ...]
"""
import json
import re
import sys

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _resolve(root, ref):
    if not ref.startswith("#/"):
        raise ValueError(f"only local $ref is supported, got {ref!r}")
    node = root
    for part in ref[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def validate(doc, schema, root=None, path="$"):
    """Return a list of error strings (empty when valid)."""
    root = schema if root is None else root
    errors = []
    if "$ref" in schema:
        return validate(doc, _resolve(root, schema["$ref"]), root, path)
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPES[t](doc) for t in types):
            return [f"{path}: expected {' or '.join(types)}, got {type(doc).__name__}"]
    if "enum" in schema and doc not in schema["enum"]:
        errors.append(f"{path}: {doc!r} is not one of {schema['enum']}")
    if "pattern" in schema and isinstance(doc, str) and not re.search(schema["pattern"], doc):
        errors.append(f"{path}: {doc!r} does not match /{schema['pattern']}/")
    if isinstance(doc, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in doc:
                errors.append(f"{path}: missing required key {key!r}")
        extra = schema.get("additionalProperties", True)
        for key, val in doc.items():
            sub = f"{path}.{key}"
            if key in props:
                errors.extend(validate(val, props[key], root, sub))
            elif extra is False:
                errors.append(f"{path}: unexpected key {key!r}")
            elif isinstance(extra, dict):
                errors.extend(validate(val, extra, root, sub))
    if isinstance(doc, list) and "items" in schema:
        for i, item in enumerate(doc):
            errors.extend(validate(item, schema["items"], root, f"{path}[{i}]"))
    return errors


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip())
        return 2
    with open(argv[0], encoding="utf-8") as fh:
        schema = json.load(fh)
    bad = 0
    for p in argv[1:]:
        with open(p, encoding="utf-8") as fh:
            errs = validate(json.load(fh), schema)
        for e in errs:
            print(f"{p}: {e}")
        bad += bool(errs)
        if not errs:
            print(f"{p}: ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
