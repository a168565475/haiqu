import unittest

from apps.ai_production_import.errors import AiOutputInvalid
from apps.ai_production_import.validation import validate_result


def field(value, source="src_1"):
    return {"value": value, "status": "EXTRACTED", "source_ids": [source], "note": ""}


class ResultValidationTests(unittest.TestCase):
    def setUp(self):
        self.source = {"source_index": {"src_1": {"kind": "cell"}}, "images": []}

    def valid_result(self):
        return {
            "task": {
                "task_number": field("HT26001"), "contract_number": field("C1"),
                "order_date": field("2026-11-11"), "delivery_date": field("2026-11-20"),
                "special_requirements": field(""),
            },
            "products": [{
                "product_key": "P1", "name": field("椅子"), "specification": field("标准"),
                "color": field("黑"), "quantity": field("10"), "unit": field("件"),
                "special_requirements": field(""),
            }],
            "boms": [{"product_key": "P1", "lines": []}],
            "issues": [],
        }

    def test_accepts_result_with_registered_sources(self):
        self.assertEqual(validate_result(self.valid_result(), self.source)["products"][0]["product_key"], "P1")

    def test_rejects_unknown_source(self):
        result = self.valid_result()
        result["products"][0]["name"]["source_ids"] = ["unknown"]
        with self.assertRaises(AiOutputInvalid) as context:
            validate_result(result, self.source)
        self.assertEqual(context.exception.code, "OPENAI_OUTPUT_SOURCE_INVALID")

    def test_rejects_invalid_task_shape(self):
        result = self.valid_result()
        result["task"] = []
        with self.assertRaises(AiOutputInvalid):
            validate_result(result, self.source)
