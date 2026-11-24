import copy
import unittest

from jsonschema import Draft202012Validator

from apps.ai_production_import.mapping import TASK_FIELDS
from apps.ai_production_import.recognition_rules import DEFAULT_RULES
from apps.ai_production_import.schema import DETAIL_SCHEMA, FIELD_SCHEMA, OUTPUT_SCHEMA


def evidence(value, status="EXTRACTED", sources=None, note=""):
    return {"value": value, "status": status, "source_ids": ["s1"] if sources is None else sources, "note": note}


class OutputSchemaContractTests(unittest.TestCase):
    def field_is_valid(self, schema, value):
        wrapper = {
            "type": "object", "properties": {"field": schema}, "required": ["field"],
            "additionalProperties": False, "$defs": OUTPUT_SCHEMA["$defs"],
        }
        return Draft202012Validator(wrapper).is_valid({"field": value})

    def test_schema_is_valid_and_uses_closed_objects_and_supported_composition(self):
        Draft202012Validator.check_schema(OUTPUT_SCHEMA)
        self.assertEqual(OUTPUT_SCHEMA["type"], "object")
        self.assertNotIn("anyOf", OUTPUT_SCHEMA)

        def inspect(schema):
            if isinstance(schema, dict):
                self.assertFalse(set(schema) & {"allOf", "not", "if", "then", "else", "dependentRequired", "dependentSchemas"})
                if schema.get("type") == "object":
                    self.assertIs(schema.get("additionalProperties"), False)
                    self.assertEqual(set(schema["properties"]), set(schema["required"]))
                for child in schema.values():
                    inspect(child)
            elif isinstance(schema, list):
                for child in schema:
                    inspect(child)

        inspect(OUTPUT_SCHEMA)

    def test_openai_references_have_no_sibling_keywords(self):
        def inspect(schema):
            if isinstance(schema, dict):
                if "$ref" in schema:
                    self.assertEqual(set(schema), {"$ref"})
                for child in schema.values():
                    inspect(child)
            elif isinstance(schema, list):
                for child in schema:
                    inspect(child)

        inspect(OUTPUT_SCHEMA)

    def test_extracted_value_requires_nonnull_value_and_nonempty_sources(self):
        for value in ("原文", 0, False):
            with self.subTest(value=value):
                self.assertTrue(self.field_is_valid(FIELD_SCHEMA, evidence(value)))
        for value in (evidence(None), evidence("原文", sources=[]), evidence("原文", sources=[""])):
            with self.subTest(value=value):
                self.assertFalse(self.field_is_valid(FIELD_SCHEMA, value))

    def test_missing_and_unreadable_require_null_without_inventing_sources(self):
        for status in ("MISSING", "UNREADABLE"):
            with self.subTest(status=status):
                self.assertTrue(self.field_is_valid(FIELD_SCHEMA, evidence(None, status, sources=[])))
                self.assertTrue(self.field_is_valid(FIELD_SCHEMA, evidence(None, status)))
                for value in ("", "原文", 0, False):
                    self.assertFalse(self.field_is_valid(FIELD_SCHEMA, evidence(value, status)))

    def test_conflict_preserves_original_value_or_null(self):
        for value in (None, "两个冲突值", 0, False):
            with self.subTest(value=value):
                self.assertTrue(self.field_is_valid(FIELD_SCHEMA, evidence(value, "CONFLICT", sources=[])))

    def test_defaults_are_only_allowed_for_the_four_confirmed_task_fields(self):
        self.assertFalse(self.field_is_valid(FIELD_SCHEMA, evidence(False, "DEFAULTED", note="D17")))
        task_fields = OUTPUT_SCHEMA["properties"]["task"]["properties"]
        for name in TASK_FIELDS:
            schema = task_fields[name]
            if name not in DEFAULT_RULES:
                with self.subTest(field=name):
                    self.assertFalse(self.field_is_valid(schema, evidence(False, "DEFAULTED", note="D17")))
                continue
            rule, value = DEFAULT_RULES[name]
            with self.subTest(field=name):
                self.assertTrue(self.field_is_valid(schema, evidence(value, "DEFAULTED", note=f"{rule} 已读且确实未填写")))
                self.assertFalse(self.field_is_valid(schema, evidence(value, "DEFAULTED", note="未注明规则")))
                self.assertFalse(self.field_is_valid(schema, evidence(value, "DEFAULTED", sources=[], note=rule)))
                self.assertFalse(self.field_is_valid(schema, evidence(None, "DEFAULTED", note=rule)))
                self.assertFalse(self.field_is_valid(schema, evidence("其他值", "DEFAULTED", note=rule)))

    def test_default_values_keep_percent_and_boolean_types_distinct(self):
        fields = OUTPUT_SCHEMA["properties"]["task"]["properties"]
        for value in (0, 0.0, "0"):
            self.assertTrue(self.field_is_valid(fields["order_tolerance_percent"], evidence(value, "DEFAULTED", note="D16")))
        for value in (False, "0%", 5):
            self.assertFalse(self.field_is_valid(fields["order_tolerance_percent"], evidence(value, "DEFAULTED", note="D16")))
        for value in (0, "false", True):
            self.assertFalse(self.field_is_valid(fields["is_repeat_order"], evidence(value, "DEFAULTED", note="D18")))

    def test_detail_values_are_boolean_or_text_and_do_not_allow_defaults(self):
        fields = DETAIL_SCHEMA["properties"]
        for value in (True, False):
            self.assertTrue(self.field_is_valid(fields["is_selected"], evidence(value)))
        for value in ("false", 0, 1):
            self.assertFalse(self.field_is_valid(fields["is_selected"], evidence(value)))
        self.assertTrue(self.field_is_valid(fields["description"], evidence("不需要丝印")))
        for value in (False, 1):
            self.assertFalse(self.field_is_valid(fields["description"], evidence(value)))
        for field in ("is_selected", "description"):
            self.assertTrue(self.field_is_valid(fields[field], evidence(None, "MISSING", sources=[])))
            self.assertFalse(self.field_is_valid(fields[field], evidence(False, "DEFAULTED", note="D17")))

    def test_main_and_additional_tasks_resolve_shared_evidence_definitions(self):
        task = {name: evidence(None, "MISSING", sources=[]) for name in TASK_FIELDS}
        task["delivery_batches"] = []
        for name, (rule, value) in DEFAULT_RULES.items():
            task[name] = evidence(value, "DEFAULTED", note=rule)
        block = {"task": task, "products": [], "boms": [], "issues": []}
        result = {**copy.deepcopy(block), "additional_tasks": [{"task_key": "second", **copy.deepcopy(block)}]}
        validator = Draft202012Validator(OUTPUT_SCHEMA)
        self.assertTrue(validator.is_valid(result))
        result["additional_tasks"][0]["task"]["includes_tax"] = evidence(False, "DEFAULTED", note="D17")
        self.assertFalse(validator.is_valid(result))
