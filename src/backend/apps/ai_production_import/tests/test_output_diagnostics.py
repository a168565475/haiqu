import copy
import unittest

from apps.ai_production_import.errors import AiOutputInvalid
from apps.ai_production_import.mapping import normalize_erp_fields
from apps.ai_production_import.tests.test_mapping import evidence, mapped_payload
from apps.ai_production_import.tests.test_recognition_contract import complete_result


class OutputDiagnosticTests(unittest.TestCase):
    def test_bad_bom_evidence_reports_field_without_source_value(self):
        result = mapped_payload()
        result["boms"][0]["lines"][0]["erp_fields"][0]["value"] = evidence("private-value", sources=[])
        with self.assertRaises(AiOutputInvalid) as caught:
            normalize_erp_fields(result)
        error = caught.exception
        self.assertEqual(error.code, "OPENAI_OUTPUT_ERP_FIELD_INVALID")
        self.assertEqual(error.path, "boms[0].lines[0].erp_fields.tube_shape")
        self.assertIn("来源编号", error.reason)
        self.assertIn(error.path, error.message)
        self.assertNotIn("private-value", error.message)

    def test_missing_field_with_value_reports_status_conflict(self):
        result = mapped_payload()
        result["products"][0]["material"] = evidence("private-value", status="MISSING")
        with self.assertRaises(AiOutputInvalid) as caught:
            normalize_erp_fields(result)
        self.assertEqual(caught.exception.path, "products[0].material")
        self.assertIn("值必须为空", caught.exception.reason)

    def test_illegal_product_default_is_still_rejected(self):
        result = mapped_payload()
        result["products"][0]["material"] = evidence("private-value", status="DEFAULTED")
        with self.assertRaises(AiOutputInvalid) as caught:
            normalize_erp_fields(result)
        self.assertEqual(caught.exception.path, "products[0].material")
        self.assertIn("没有已确认的默认规则", caught.exception.reason)

    def test_additional_task_error_identifies_its_own_task_and_rule(self):
        result = mapped_payload()
        block = copy.deepcopy(result)
        block["task_key"] = "second"
        block["task"]["delivery_method"] = evidence("SINGLE", status="DEFAULTED")
        result["additional_tasks"] = [block]
        with self.assertRaises(AiOutputInvalid) as caught:
            normalize_erp_fields(result)
        self.assertEqual(caught.exception.path, "additional_tasks[0].task.delivery_method")
        self.assertIn("D23", caught.exception.reason)

    def test_detail_string_boolean_reports_exact_field(self):
        result = complete_result()
        result["products"][0]["details"][0]["is_selected"] = evidence("true")
        with self.assertRaises(AiOutputInvalid) as caught:
            normalize_erp_fields(result)
        self.assertEqual(caught.exception.path, "products[0].details[0].is_selected")
        self.assertIn("true、false 或空值", caught.exception.reason)

    def test_distinct_failures_have_distinct_user_messages(self):
        codes = ["OPENAI_OUTPUT_ERP_FIELD_INVALID", "OPENAI_OUTPUT_SOURCE_INVALID", "OPENAI_OUTPUT_SCHEMA_INVALID"]
        self.assertEqual(len({AiOutputInvalid(code).message for code in codes}), 3)

    def test_duplicate_sparse_field_reports_index_without_echoing_unknown_key(self):
        for key in ("tube_shape", "private-unknown-key"):
            result = mapped_payload()
            fields = result["boms"][0]["lines"][0]["erp_fields"]
            fields.append({"field": key, "value": evidence("private-value")})
            with self.subTest(key=key), self.assertRaises(AiOutputInvalid) as caught:
                normalize_erp_fields(result)
            self.assertEqual(caught.exception.path, "boms[0].lines[0].erp_fields[4].field")
            self.assertNotIn("private-", caught.exception.message)

    def test_duplicate_bom_line_reports_second_line(self):
        result = mapped_payload()
        lines = result["boms"][0]["lines"]
        lines.append(copy.deepcopy(lines[0]))
        with self.assertRaises(AiOutputInvalid) as caught:
            normalize_erp_fields(result)
        self.assertEqual(caught.exception.path, "boms[0].lines[1].line_key")
        self.assertIn("重复", caught.exception.reason)
