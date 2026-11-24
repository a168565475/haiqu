import copy
import unittest

from apps.ai_production_import.field_coverage import complete_tube_field_coverage


def evidence(value, sources=(), status="EXTRACTED"):
    return {"value": value, "source_ids": list(sources), "status": status, "note": ""}


def source_sheet(name="任意名称", part="sheet-a", count="11", row=10):
    values = {f"D{row}": "交叉管", f"M{row - 1}": "原材料长度(M)", f"M{row}": "5.99",
              f"N{row}": "切", f"O{row}": count, f"P{row}": "支", f"Q{row - 1}": "支数", f"Q{row}": "827.46"}
    cells = [{"ref": ref, "text": text, "source_id": f"{part}-{ref}"} for ref, text in values.items()]
    return {"name": name, "part": part, "cells": cells, "merged_cells": [f"M{row - 1}:P{row - 1}", f"Q{row - 1}:R{row - 1}"]}


def controlled(*sheets):
    return {"sheets": list(sheets), "source_index": {
        cell["source_id"]: {"kind": "cell", "sheet_part": sheet["part"], "ref": cell["ref"]}
        for sheet in sheets for cell in sheet["cells"]}}


def tube_line(part="sheet-a", row=10):
    return {"line_key": "pipe-1", "section": "管材类", "part_name": evidence("交叉管", [f"{part}-D{row}"]),
            "raw_content": evidence("模型原文故意写切999支，补齐必须取真实单元格", [f"{part}-{col}{row}" for col in ("D", "M", "N", "O", "P", "Q")]),
            "quantity_basis": "UNIT_CONSUMPTION", "quantity": evidence(6, [f"{part}-D{row}"]),
            "unit": evidence("支", [f"{part}-P{row}"]),
            "erp_fields": {"length_value": evidence(540, [f"{part}-D{row}"]), "unit_consumption": evidence(6, [f"{part}-D{row}"])}}


def result_for(*lines):
    return {"task": {}, "products": [], "boms": [{"product_key": "product-1", "lines": list(lines)}], "issues": []}


def field(result, name="tube_cut_piece_count"):
    return result["boms"][0]["lines"][0]["erp_fields"][name]


class TubeFieldCoverageTests(unittest.TestCase):
    def test_recovers_split_source_cells_without_using_model_raw_or_mutating_inputs(self):
        source, result = controlled(source_sheet()), result_for(tube_line())
        original_source, original_result = copy.deepcopy(source), copy.deepcopy(result)
        actual = complete_tube_field_coverage(result, source)
        self.assertEqual(field(actual)["value"], 11)
        self.assertEqual(field(actual)["status"], "EXTRACTED")
        self.assertIn("sheet-a-O10", field(actual)["source_ids"])
        self.assertIn("sheet-a-M9", field(actual)["source_ids"])
        self.assertEqual(actual["issues"], [])
        self.assertEqual(source, original_source)
        self.assertEqual(result, original_result)

    def test_different_sheet_row_and_columns_do_not_depend_on_original_template_coordinates(self):
        sheet = source_sheet("布局改变", "shifted", "8", row=25)
        remap = {"D25": "B25", "M24": "F24", "M25": "F25", "N25": "G25", "O25": "H25", "P25": "I25", "Q24": "J24", "Q25": "J25"}
        for cell in sheet["cells"]:
            cell["ref"] = remap[cell["ref"]]
            cell["source_id"] = f"shifted-{cell['ref']}"
        sheet["merged_cells"] = ["F24:I24", "J24:K24"]
        line = tube_line("shifted", 25)
        line["part_name"]["source_ids"] = ["shifted-B25"]
        line["raw_content"]["source_ids"] = [f"shifted-{ref}" for ref in ["B25", "G25", "H25", "I25"]]
        actual = complete_tube_field_coverage(result_for(line), controlled(sheet))
        self.assertEqual(field(actual)["value"], 8)

    def test_two_tasks_with_same_material_name_keep_their_own_sheet_and_count(self):
        first, second = source_sheet(count="11"), source_sheet("夹棉资料", "sheet-b", "9")
        result = result_for(tube_line())
        result["additional_tasks"] = [{"task_key": "second", **result_for(tube_line("sheet-b"))}]
        actual = complete_tube_field_coverage(result, controlled(first, second))
        self.assertEqual(field(actual)["value"], 11)
        self.assertEqual(field(actual["additional_tasks"][0])["value"], 9)

    def test_reads_explicit_cut_count_column_but_never_plain_purchase_count_header(self):
        for header, expected in [("每根切割支数（支）", 11), ("切割支数", 11), ("支数", None), ("采购支数", None)]:
            with self.subTest(header=header):
                sheet = source_sheet()
                sheet["merged_cells"] = []
                sheet["cells"] = [cell for cell in sheet["cells"] if cell["ref"] not in {"N10", "P10", "M9"}]
                sheet["cells"].append({"ref": "O9", "text": header, "source_id": "sheet-a-O9"})
                actual = complete_tube_field_coverage(result_for(tube_line()), controlled(sheet))
                self.assertEqual(field(actual)["value"], expected)
                if expected is None:
                    self.assertEqual(field(actual)["status"], "MISSING")

    def test_unknown_raw_text_without_cell_evidence_is_not_parsed_as_authority(self):
        sheet = source_sheet()
        sheet["cells"] = [cell for cell in sheet["cells"] if cell["ref"] not in {"N10", "O10", "P10"}]
        actual = complete_tube_field_coverage(result_for(tube_line()), controlled(sheet))
        self.assertEqual(field(actual)["status"], "MISSING")
        self.assertEqual(len(actual["issues"]), 1)
        self.assertIn("每根切割支数", actual["issues"][0]["message"])

    def test_requires_all_three_inline_cells_to_be_referenced_by_this_line(self):
        for missing in ("N10", "O10", "P10", "D10"):
            with self.subTest(missing=missing):
                line = tube_line()
                line["raw_content"]["source_ids"].remove(f"sheet-a-{missing}")
                actual = complete_tube_field_coverage(result_for(line), controlled(source_sheet()))
                self.assertEqual(field(actual)["status"], "MISSING")

    def test_requires_raw_length_group_and_does_not_cross_new_group_heading(self):
        for title in ("采购数量", "加工数量", "说明", ""):
            with self.subTest(title=title):
                sheet = source_sheet()
                next(cell for cell in sheet["cells"] if cell["ref"] == "M9")["text"] = title
                actual = complete_tube_field_coverage(result_for(tube_line()), controlled(sheet))
                self.assertEqual(field(actual)["status"], "MISSING")

    def test_nonpositive_fractional_and_out_of_range_counts_remain_pending(self):
        for count in ("0", "-1", "1.5", "2147483648", "NaN", "11支", ""):
            with self.subTest(count=count):
                actual = complete_tube_field_coverage(result_for(tube_line()), controlled(source_sheet(count=count)))
                self.assertEqual(field(actual)["status"], "MISSING")

    def test_multiple_name_rows_or_wrong_name_cannot_select_a_material_row(self):
        first, second = source_sheet(), source_sheet("第二份", "sheet-b", "9")
        for wrong_name in (False, True):
            with self.subTest(wrong_name=wrong_name):
                line = tube_line()
                if wrong_name:
                    line["part_name"]["value"] = "扶手管"
                else:
                    line["part_name"]["source_ids"].append("sheet-b-D10")
                    line["raw_content"]["source_ids"].extend([f"sheet-b-{col}10" for col in ("D", "N", "O", "P")])
                actual = complete_tube_field_coverage(result_for(line), controlled(first, second))
                self.assertEqual(field(actual)["status"], "MISSING")

    def test_mismatched_source_index_is_not_accepted(self):
        source = controlled(source_sheet())
        source["source_index"]["sheet-a-O10"]["ref"] = "O11"
        actual = complete_tube_field_coverage(result_for(tube_line()), source)
        self.assertEqual(field(actual)["status"], "MISSING")

    def test_two_explicit_counts_in_same_row_are_a_conflict(self):
        sheet = source_sheet()
        sheet["cells"].extend([{"ref": "T9", "text": "每根切割支数", "source_id": "sheet-a-T9"},
                               {"ref": "T10", "text": "12", "source_id": "sheet-a-T10"}])
        line = tube_line()
        line["raw_content"]["source_ids"].append("sheet-a-T10")
        actual = complete_tube_field_coverage(result_for(line), controlled(sheet))
        self.assertEqual(field(actual)["status"], "CONFLICT")
        self.assertIsNone(field(actual)["value"])
        self.assertEqual(actual["issues"][0]["kind"], "BOM_FIELD_CONFLICT")
        self.assertIn("O10=11", field(actual)["note"])
        self.assertIn("T10=12", field(actual)["note"])

    def test_existing_extracted_conflict_and_unreadable_fields_are_never_overwritten(self):
        for status, value in [("EXTRACTED", 7), ("CONFLICT", None), ("UNREADABLE", None)]:
            with self.subTest(status=status):
                line = tube_line()
                supplied = evidence(value, ["sheet-a-O10"], status)
                line["erp_fields"]["tube_cut_piece_count"] = supplied
                actual = complete_tube_field_coverage(result_for(line), controlled(source_sheet()))
                self.assertEqual(field(actual), supplied)

    def test_missing_field_can_recover_and_repeat_calls_are_idempotent(self):
        line = tube_line()
        line["erp_fields"]["tube_cut_piece_count"] = evidence(None, [], "MISSING")
        actual = complete_tube_field_coverage(result_for(line), controlled(source_sheet()))
        self.assertEqual(field(actual)["value"], 11)
        self.assertEqual(complete_tube_field_coverage(actual, controlled(source_sheet())), actual)
        pending = complete_tube_field_coverage(result_for(tube_line()), controlled())
        self.assertEqual(complete_tube_field_coverage(pending, controlled()), pending)

    def test_missing_length_and_unit_consumption_are_explicitly_reported_without_inventing_values(self):
        line = tube_line()
        line["erp_fields"] = {}
        line["quantity_basis"] = "MANUFACTURING_TOTAL"
        actual = complete_tube_field_coverage(result_for(line), controlled(source_sheet()))
        self.assertEqual(field(actual, "length_value")["status"], "MISSING")
        self.assertEqual(field(actual, "unit_consumption")["status"], "MISSING")
        self.assertEqual(field(actual)["value"], 11)
        self.assertEqual(len(actual["issues"]), 2)

    def test_explicit_per_product_quantity_copies_evidence_into_unit_consumption(self):
        line = tube_line()
        del line["erp_fields"]["unit_consumption"]
        actual = complete_tube_field_coverage(result_for(line), controlled(source_sheet()))
        self.assertEqual(field(actual, "unit_consumption")["value"], 6)
        self.assertEqual(field(actual, "unit_consumption")["source_ids"], line["quantity"]["source_ids"])
        for missing in ("quantity", "unit"):
            incomplete = copy.deepcopy(line)
            incomplete[missing] = evidence(None, [], "MISSING")
            pending = complete_tube_field_coverage(result_for(incomplete), controlled(source_sheet()))
            self.assertEqual(field(pending, "unit_consumption")["status"], "MISSING")

    def test_non_pipe_sections_and_original_issues_are_preserved(self):
        line = tube_line()
        line["section"] = "五金件"
        result = result_for(line)
        result["issues"] = [{"issue_key": "original", "kind": "MATERIAL", "message": "原问题", "source_ids": []}]
        self.assertEqual(complete_tube_field_coverage(result, controlled(source_sheet())), result)

    def test_recovered_field_clears_only_its_previously_generated_issue(self):
        result = complete_tube_field_coverage(result_for(tube_line()), controlled())
        other = {"issue_key": "original", "kind": "MATERIAL", "message": "原问题", "source_ids": []}
        result["issues"].append(other)
        actual = complete_tube_field_coverage(result, controlled(source_sheet()))
        self.assertEqual(field(actual)["value"], 11)
        self.assertEqual(actual["issues"], [other])
