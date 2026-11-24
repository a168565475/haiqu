import copy
import unittest

from apps.ai_production_import.review_recovery import recover_empty_review_cut_counts


def fixture():
    field = lambda value: {"value": value, "status": "EXTRACTED", "source_ids": ["s1"], "note": ""}
    line = {"line_key": "l1", "section": "管材类", "part_name": field("交叉管"),
            "erp_fields": {"length_value": field(540), "source_raw_bar_length_m": field("5.990")}}
    result = {"boms": [{"product_key": "p1", "lines": [line]}], "additional_tasks": []}
    recovered = copy.deepcopy(result)
    recovered["boms"][0]["lines"][0]["erp_fields"]["tube_cut_piece_count"] = field(11)
    draft = {"task_key": "main", "task_payload": {"task_number": "人工任务名"},
             "bom_plans": [{"product_key": "p1", "sections": [{"title": "管材类", "lines": [{
                 "ai_line_key": "l1", "part_name": "交叉管", "length_value": "540", "source_raw_bar_length_m": "5.99",
                 "tube_cut_piece_count": "", "notes": "人工备注", "ai_original_text": "原文已调整", "ai_source": copy.deepcopy(line),
             }]}]}]}
    source = {"sheets": [{"cells": [{"text": "原始单元格"}]}], "review_draft": draft,
              "task_states": {"main": {"review_draft": copy.deepcopy(draft)}}}
    return result, recovered, source


class ReviewRecoveryTests(unittest.TestCase):
    def test_only_recovers_empty_value_and_preserves_other_user_fields_and_source(self):
        args = fixture()
        before = copy.deepcopy(args)
        result, source, changes = recover_empty_review_cut_counts(*args)
        line = source["review_draft"]["bom_plans"][0]["sections"][0]["lines"][0]
        self.assertEqual(line["tube_cut_piece_count"], "11")
        self.assertEqual(line["notes"], "人工备注")
        self.assertEqual(line["ai_original_text"], "原文已调整")
        self.assertEqual(source["review_draft"]["task_payload"], before[2]["review_draft"]["task_payload"])
        self.assertEqual(source["sheets"], before[2]["sheets"])
        self.assertEqual(len(changes), 3)
        self.assertEqual(args, before)
        self.assertEqual(recover_empty_review_cut_counts(result, args[1], source)[2], [])

    def test_does_not_overwrite_manual_values_or_changed_material_basis(self):
        for key, value in (("tube_cut_piece_count", "12"), ("tube_cut_piece_count", 0),
                           ("tube_cut_piece_count", False), ("length_value", "600"),
                           ("source_raw_bar_length_m", "6.5"), ("part_name", "人工换材料")):
            with self.subTest(key=key, value=value):
                result, recovered, source = fixture()
                source["task_states"] = {}
                source["review_draft"]["bom_plans"][0]["sections"][0]["lines"][0][key] = value
                before = copy.deepcopy(source["review_draft"])
                _, actual, changes = recover_empty_review_cut_counts(result, recovered, source)
                self.assertEqual(actual["review_draft"], before)
                self.assertEqual(len(changes), 1)

    def test_duplicate_line_names_in_other_tasks_and_unreadable_fields_are_not_overwritten(self):
        result, recovered, source = fixture()
        source["review_draft"]["task_key"] = "second"
        source["task_states"] = {}
        before = copy.deepcopy(source["review_draft"])
        _, actual, _ = recover_empty_review_cut_counts(result, recovered, source)
        self.assertEqual(actual["review_draft"], before)
        for status in ("CONFLICT", "UNREADABLE", "EXTRACTED"):
            result["boms"][0]["lines"][0]["erp_fields"]["tube_cut_piece_count"] = {
                "value": None if status != "EXTRACTED" else 13, "status": status, "source_ids": [], "note": "人工核对"}
            _, _, changes = recover_empty_review_cut_counts(result, recovered, source)
            self.assertEqual(changes, [])
