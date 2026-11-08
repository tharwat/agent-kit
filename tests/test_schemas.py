# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""manifest.json and every pack.json validate against schemas/; the validator itself works."""
import os
import unittest

from kit_testlib import KIT, load_json, manifest, schema_check, unit_files

PACK_SCHEMA = load_json(os.path.join(KIT, "schemas", "pack.schema.json"))
MANIFEST_SCHEMA = load_json(os.path.join(KIT, "schemas", "manifest.schema.json"))


class SchemaFiles(unittest.TestCase):
    def test_schemas_declare_draft_2020_12(self):
        for s in (PACK_SCHEMA, MANIFEST_SCHEMA):
            self.assertEqual(s["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_manifest_validates(self):
        self.assertEqual(schema_check.validate(manifest(), MANIFEST_SCHEMA), [])

    def test_every_pack_json_validates(self):
        for name, path in unit_files().items():
            with self.subTest(unit=name):
                errs = schema_check.validate(load_json(path), PACK_SCHEMA)
                self.assertEqual(errs, [], f"{os.path.relpath(path, KIT)}:\n  " + "\n  ".join(errs))

    def test_pack_name_matches_folder(self):
        for name, path in unit_files().items():
            folder = os.path.basename(os.path.dirname(path))
            with self.subTest(unit=name):
                self.assertEqual(name, folder)

    def test_manifest_lists_every_unit_on_disk(self):
        on_disk = {os.path.relpath(p, KIT).replace(os.sep, "/") for p in unit_files().values()}
        listed = set(manifest()["units"])
        self.assertEqual(sorted(on_disk - listed), [], "pack.json files missing from manifest.json units")
        self.assertEqual(sorted(listed - on_disk), [], "manifest.json units that don't exist")

    def test_core_kind_is_core_and_only_core(self):
        for name, path in unit_files().items():
            with self.subTest(unit=name):
                self.assertEqual(load_json(path).get("kind") == "core", name == "core")

    def test_pack_requires_and_conflicts_name_real_units(self):
        units = set(unit_files())
        for name, path in unit_files().items():
            d = load_json(path)
            for r in d.get("requires", []) + d.get("conflicts", []):
                with self.subTest(unit=name, ref=r):
                    self.assertIn(r, units)


class Validator(unittest.TestCase):
    S = {"type": "object", "required": ["a"], "additionalProperties": False,
         "properties": {"a": {"type": "string", "pattern": "^x"}, "b": {"type": "array", "items": {"$ref": "#/$defs/n"}},
                        "c": {"enum": [1, 2]}, "d": {"type": ["string", "null"]}},
         "$defs": {"n": {"type": "integer"}}}

    def test_valid(self):
        self.assertEqual(schema_check.validate({"a": "xy", "b": [1, 2], "c": 2, "d": None}, self.S), [])

    def test_each_keyword_reports(self):
        cases = [({}, "missing required"), ({"a": 1}, "expected string"), ({"a": "y"}, "does not match"),
                 ({"a": "x", "z": 1}, "unexpected key"), ({"a": "x", "b": [True]}, "expected integer"),
                 ({"a": "x", "c": 3}, "is not one of"), ({"a": "x", "d": 5}, "expected string or null")]
        for doc, msg in cases:
            with self.subTest(doc=doc):
                errs = schema_check.validate(doc, self.S)
                self.assertTrue(any(msg in e for e in errs), errs)

    def test_additional_properties_schema(self):
        s = {"type": "object", "additionalProperties": {"type": "string"}}
        self.assertEqual(schema_check.validate({"k": "v"}, s), [])
        self.assertTrue(schema_check.validate({"k": 1}, s))

    def test_pack_schema_rejects_absolute_hook_path_and_secret_env(self):
        bad = {"name": "x", "version": "1.0.0", "description": "d", "kind": "extra", "files": [],
               "hooks": [{"event": "PreToolUse", "command": "/abs/path/hook.sh"}],
               "mcp": {"s": {"type": "stdio", "command": "x", "env": {"TOKEN": "literal-value"}}}}
        errs = schema_check.validate(bad, PACK_SCHEMA)
        self.assertTrue(any("hooks[0].command" in e for e in errs), errs)
        self.assertTrue(any("env.TOKEN" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
