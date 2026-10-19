from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from apps.products.models import RawMaterialInformation
from ..material_flow_calculations import CUTTING_USAGE_FIELDS, MaterialFlowValueError, cutting_usage_plan
from ..models import BomLine
from ..services import create_bom, sync_latest_boms_from_order
from . import test_material_flow_bom as fixtures


class CuttingUsageCalculationTests(SimpleTestCase):
    def test_two_pieces_make_one_set_without_doubling_output_sets(self):
        result = cutting_usage_plan(cutting_pieces_per_set=2, fabric_meters_per_piece="0.125",
                                    cutting_sets_per_product=1, order_quantity=105)
        self.assertEqual((result["required_sets"], result["required_pieces"], result["required_meters"]),
                         (105, 210, "26.2500"))
        self.assertEqual(result["fabric_meters_per_set"], "0.2500")

    def test_multiple_sets_per_product_are_separate_from_pieces(self):
        result = cutting_usage_plan(cutting_pieces_per_set=2, fabric_meters_per_piece="0.125",
                                    cutting_sets_per_product=3, order_quantity=105)
        self.assertEqual((result["required_sets"], result["required_pieces"], result["required_meters"]),
                         (315, 630, "78.7500"))

    def test_all_missing_does_not_guess_legacy_values(self):
        self.assertIsNone(cutting_usage_plan(order_quantity=105))

    def test_partial_zero_fractional_and_nonfinite_inputs_are_rejected(self):
        valid = dict(cutting_pieces_per_set=2, fabric_meters_per_piece="0.125",
                     cutting_sets_per_product=1, order_quantity=105)
        cases = [(field, None) for field in CUTTING_USAGE_FIELDS]
        cases += [(field, "0") for field in CUTTING_USAGE_FIELDS]
        cases += [("cutting_pieces_per_set", "1.5"), ("cutting_sets_per_product", True),
                  ("fabric_meters_per_piece", "NaN"), ("fabric_meters_per_piece", "0.00001")]
        for field, value in cases:
            with self.subTest(field=field, value=value), self.assertRaises(MaterialFlowValueError):
                cutting_usage_plan(**{**valid, field: value})

    def test_each_derived_quantity_is_checked_for_overflow(self):
        for values in [
            dict(cutting_pieces_per_set=2, fabric_meters_per_piece="99999999999999.9999", cutting_sets_per_product=1, order_quantity=1),
            dict(cutting_pieces_per_set=1, fabric_meters_per_piece="0.0001", cutting_sets_per_product=2, order_quantity=99999999999999),
            dict(cutting_pieces_per_set=2, fabric_meters_per_piece="0.0001", cutting_sets_per_product=1, order_quantity=99999999999999),
            dict(cutting_pieces_per_set=1, fabric_meters_per_piece="99999999999999.9999", cutting_sets_per_product=1, order_quantity=2),
        ]:
            with self.subTest(values=values), self.assertRaises(MaterialFlowValueError):
                cutting_usage_plan(**values)
        maximum = cutting_usage_plan(cutting_pieces_per_set=1, fabric_meters_per_piece="99999999999999.9999",
                                     cutting_sets_per_product=1, order_quantity=1)
        self.assertEqual(maximum["required_meters"], "99999999999999.9999")


class CuttingUsageBomTests(TestCase):
    setUpFixture = fixtures.MaterialFlowBomTests.setUpFixture
    tearDown = fixtures.MaterialFlowBomTests.tearDown
    material = fixtures.MaterialFlowBomTests.material
    get = fixtures.MaterialFlowBomTests.get
    save = fixtures.MaterialFlowBomTests.save
    pipe_payload = fixtures.MaterialFlowBomTests.pipe_payload
    initial = fixtures.MaterialFlowBomTests.initial
    verify = fixtures.MaterialFlowBomTests.verify

    def setUp(self):
        fixtures.MaterialFlowBomTests.setUp(self)
        self.initial()
        self.fabric_line, self.cutting_line = fixtures.MaterialFlowBomTests.add_fabric_and_cutting(self)

    def save_cutting(self, **changes):
        sections = self.get().data["data"]["sections"]
        row = next(section for section in sections if section["title"] == "裁剪明细")["lines"][0]
        row.update(changes)
        return self.save(sections)

    def enable_piece_usage(self, **changes):
        response = self.save_cutting(cutting_pieces_per_set=2, fabric_meters_per_piece="0.1250",
                                    cutting_sets_per_product=3, **changes)
        self.assertEqual(response.status_code, 200, response.data)
        self.cutting_line.refresh_from_db()
        return response

    def attach_stable_cutting_source(self):
        source = RawMaterialInformation.objects.filter(item_type="SEMI_FINISHED", archived_at__isnull=True,
            category__status="ACTIVE", category__archived_at__isnull=True).first()
        self.assertIsNotNone(source)
        self.cutting_line.raw_values = {**self.cutting_line.raw_values,
            "source_inventory_material_id": str(source.pk), "source_cutting_material_id": str(source.pk),
            "cutting_color": "黑色"}
        self.cutting_line.material = "PVC"
        self.cutting_line.specification = "400 × 600 mm"
        self.cutting_line.save()
        return source

    def test_stable_cutting_source_preserves_edited_attributes_ids_and_usage(self):
        response = self.save_cutting(cutting_pieces_per_set=2, fabric_meters_per_piece="0.1250",
                                    cutting_sets_per_product=1)
        self.assertEqual(response.status_code, 200, response.data)
        self.cutting_line.refresh_from_db()
        source = self.attach_stable_cutting_source()
        source_before = RawMaterialInformation.objects.filter(pk=source.pk).values().get()
        fabric_before = BomLine.objects.filter(pk=self.fabric_line.pk).values(
            "unit_consumption", "total_consumption", "total_purchase_quantity", "raw_values").get()
        component_identity = self.cutting_line.component_identity

        response = self.save_cutting(material="PE", specification="125 × 1500 mm",
                                    cutting_color="5865C", unit="片")
        self.assertEqual(response.status_code, 200, response.data)
        row = next(section for section in self.get().data["data"]["sections"]
                   if section["title"] == "裁剪明细")["lines"][0]
        self.assertEqual((row["material"], row["specification"], row["cutting_color"], row["unit"]),
                         ("PE", "125 × 1500 mm", "5865C", "套"))
        self.assertEqual((row["source_inventory_material_id"], row["source_cutting_material_id"]),
                         (str(source.pk), str(source.pk)))
        self.cutting_line.refresh_from_db()
        self.assertEqual(self.cutting_line.component_identity, component_identity)
        self.assertEqual(self.cutting_line.fabric_source_line_id, self.fabric_line.pk)
        self.assertEqual((self.cutting_line.cutting_pieces_per_set, self.cutting_line.fabric_meters_per_piece,
                          self.cutting_line.cutting_sets_per_product, self.cutting_line.fabric_meters_per_set,
                          self.cutting_line.total_consumption, self.cutting_line.total_purchase_quantity),
                         (2, Decimal("0.125"), 1, Decimal("0.25"), "250.0000", ""))
        self.assertEqual(RawMaterialInformation.objects.filter(pk=source.pk).values().get(), source_before)
        self.assertEqual(BomLine.objects.filter(pk=self.fabric_line.pk).values(
            "unit_consumption", "total_consumption", "total_purchase_quantity", "raw_values").get(), fabric_before)

    def test_stable_cutting_omitted_fields_keep_snapshot_and_cannot_clear_source(self):
        source = self.attach_stable_cutting_source()
        sections = self.get().data["data"]["sections"]
        row = next(section for section in sections if section["title"] == "裁剪明细")["lines"][0]
        for field in ("material", "specification", "unit", "source_inventory_material_id"):
            row.pop(field)
        response = self.save(sections)
        self.assertEqual(response.status_code, 200, response.data)
        self.cutting_line.refresh_from_db()
        self.assertEqual((self.cutting_line.material, self.cutting_line.specification, self.cutting_line.unit),
                         ("PVC", "400 × 600 mm", "套"))
        self.assertEqual(self.cutting_line.raw_values["source_inventory_material_id"], str(source.pk))
        before = BomLine.objects.filter(pk=self.cutting_line.pk).values().get()
        self.assertEqual(self.save_cutting(source_inventory_material_id=None).status_code, 400)
        self.assertEqual(BomLine.objects.filter(pk=self.cutting_line.pk).values().get(), before)

    def test_fabric_snapshot_remains_authoritative_and_partial_pipe_edit_requires_completion(self):
        sections = self.get().data["data"]["sections"]
        expected = {}
        for section in sections:
            if section["title"] not in {"管材类", "面料类"}:
                continue
            row = section["lines"][0]
            expected[row["id"]] = {field: row[field] for field in
                ("material", "specification", "unit", "source_inventory_material_id")}
            row.update(material="伪造材质", specification="伪造规格", unit="伪造单位")
        response = self.save(sections)
        self.assertEqual(response.status_code, 200, response.data)
        for section in response.data["data"]["sections"]:
            for row in section["lines"]:
                if row["id"] in expected:
                    if section["title"] == "管材类":
                        self.assertEqual(row["material"], "伪造材质")
                        self.assertEqual(row["source_inventory_material_id"], expected[row["id"]]["source_inventory_material_id"])
                        self.assertEqual(row["unit"], "根")
                        self.assertTrue(row["raw_values"]["pipe_source_sync_pending"])
                    else:
                        self.assertEqual({field: row[field] for field in expected[row["id"]]}, expected[row["id"]])
        self.assertEqual(self.verify().status_code, 400)

    def test_save_recalculates_forged_derived_values_without_rewriting_fabric_usage(self):
        self.enable_piece_usage(fabric_meters_per_set="999", cut_piece_quantity="99", unit_consumption="99",
                                total_consumption="999", total_purchase_quantity="999", unit="片")
        line = self.cutting_line
        self.assertEqual((line.fabric_meters_per_set, line.cut_piece_quantity, line.unit_consumption, line.unit),
                         (Decimal("0.25"), "2", "0.1250", "套"))
        self.assertEqual((line.total_consumption, line.total_purchase_quantity), ("750.0000", ""))
        self.fabric_line.refresh_from_db()
        self.assertEqual(self.fabric_line.unit_consumption, "2.5")
        self.assertEqual(Decimal(self.fabric_line.total_purchase_quantity), 2500)
        row = next(section for section in self.get().data["data"]["sections"] if section["title"] == "裁剪明细")["lines"][0]
        self.assertEqual((row["cutting_pieces_per_set"], row["fabric_meters_per_piece"], row["cutting_sets_per_product"]),
                         (2, "0.1250", 3))

    def test_new_row_requires_complete_bundle_when_new_fields_are_used(self):
        source = RawMaterialInformation.objects.filter(item_type="SEMI_FINISHED", archived_at__isnull=True,
            category__status="ACTIVE", category__archived_at__isnull=True).first()
        self.assertIsNotNone(source)
        sections = self.get().data["data"]["sections"]
        rows = next(section for section in sections if section["title"] == "裁剪明细")["lines"]
        rows.append({"part_name": source.material_name, "specification": "400 × 600 mm", "source_cutting_material_id": str(source.pk), "fabric_source_line_id": str(self.fabric_line.pk),
                     "cutting_pieces_per_set": 2})
        invalid = self.save(sections)
        self.assertEqual(invalid.status_code, 400, invalid.data)
        self.assertIn("必须同时填写", str(invalid.data))
        self.assertEqual(BomLine.objects.filter(section__bom=self.bom, section__title="裁剪明细").count(), 1)
        rows[-1].update(fabric_meters_per_piece="0.125", cutting_sets_per_product=1)
        response = self.save(sections)
        self.assertEqual(response.status_code, 200, response.data)
        created = BomLine.objects.get(section__bom=self.bom, section__title="裁剪明细", line_number=2)
        self.assertEqual((created.fabric_meters_per_set, created.unit, created.total_consumption),
                         (Decimal("0.25"), "套", "250.0000"))

    def test_new_mode_cannot_be_partly_or_fully_cleared_and_rolls_back(self):
        self.enable_piece_usage()
        before = list(BomLine.objects.filter(section__bom=self.bom).order_by("pk").values())
        for changes in [{field: None for field in CUTTING_USAGE_FIELDS}, {"fabric_meters_per_piece": None}]:
            self.assertEqual(self.save_cutting(**changes).status_code, 400)
            self.assertEqual(list(BomLine.objects.filter(section__bom=self.bom).order_by("pk").values()), before)

    def test_invalid_input_and_overflow_are_business_errors_without_partial_save(self):
        self.enable_piece_usage()
        for changes in [dict(cutting_pieces_per_set="1.5"), dict(cutting_sets_per_product=0),
                        dict(fabric_meters_per_piece="0.00001"), dict(cutting_pieces_per_set=100000000000000),
                        dict(fabric_meters_per_piece="99999999999999.9999")]:
            with self.subTest(changes=changes):
                self.assertEqual(self.save_cutting(**changes).status_code, 400)
        self.cutting_line.refresh_from_db()
        self.assertEqual(self.cutting_line.total_consumption, "750.0000")

    def test_verify_recalculates_copy_relinks_and_order_sync_preserves_old_version(self):
        self.enable_piece_usage()
        BomLine.objects.filter(pk=self.cutting_line.pk).update(fabric_meters_per_set=99, total_consumption="99")
        response = self.verify()
        self.assertEqual(response.status_code, 200, response.data)
        self.cutting_line.refresh_from_db()
        self.assertEqual(self.cutting_line.total_consumption, "750.0000")
        self.product_line.quantity = 1001
        self.product_line.save()
        copied = sync_latest_boms_from_order(product_line_ids=[self.product_line.pk], actor_employee=self.employee, request=None)[0]
        self.assertNotEqual(copied.pk, self.bom.pk)
        line = BomLine.objects.get(section__bom=copied, section__title="裁剪明细")
        self.assertEqual((line.cutting_pieces_per_set, line.fabric_meters_per_piece, line.cutting_sets_per_product),
                         (2, Decimal("0.125"), 3))
        self.assertEqual(line.total_consumption, "750.7500")
        self.assertNotEqual(line.fabric_source_line_id, self.fabric_line.pk)
        self.assertEqual(line.fabric_source_line.section.bom_id, copied.pk)
        self.cutting_line.refresh_from_db()
        self.assertEqual(self.cutting_line.total_consumption, "750.0000")

    def test_legacy_save_confirm_and_copy_do_not_guess_or_change_old_cutting_quantities(self):
        self.cutting_line.cut_piece_quantity = "2"
        self.cutting_line.unit_consumption = ""
        self.cutting_line.total_consumption = "old"
        self.cutting_line.save()
        response = self.save_cutting()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.verify().status_code, 200)
        copied = create_bom(product_line=self.product_line, creation_method="COPY", source_bom=self.bom, actor_employee=self.employee)
        for line in [BomLine.objects.get(pk=self.cutting_line.pk), BomLine.objects.get(section__bom=copied, section__title="裁剪明细")]:
            self.assertTrue(all(getattr(line, field) is None for field in CUTTING_USAGE_FIELDS))
            self.assertEqual((line.cut_piece_quantity, line.unit_consumption, line.fabric_meters_per_set, line.total_consumption),
                             ("2", "", Decimal("1.5"), "old"))

    def test_database_rejects_partial_bundle_even_without_api(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            BomLine.objects.filter(pk=self.cutting_line.pk).update(cutting_pieces_per_set=2)
