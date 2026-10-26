"""采购保存后的材料身份独立于 BOM，旧单仅按已保存原料编号兼容。"""
from copy import deepcopy
from uuid import uuid4

from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.boms.models import BomLine, BomSectionType
from apps.core.api.exceptions import Conflict
from apps.procurement.models import PurchaseOrder, PurchaseOrderLine
from apps.procurement.tests import test_pipe_purchase_flow as pipe_fixture
from apps.procurement.tests import test_purchase_order_api as purchase_fixture
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductionUnit


class SavedPurchaseMaterialIdentityTests(APITestCase):
    setUp = purchase_fixture.PurchaseOrderApiTests.setUp
    make_task = purchase_fixture.PurchaseOrderApiTests.make_task
    make_product_line = purchase_fixture.PurchaseOrderApiTests.make_product_line
    make_bom = purchase_fixture.PurchaseOrderApiTests.make_bom
    get_source = purchase_fixture.PurchaseOrderApiTests.get_source
    create_payload = staticmethod(purchase_fixture.PurchaseOrderApiTests.create_payload)

    def create_material_purchase(self, suffix="IDENTITY"):
        task = self.make_task(suffix)
        product_line = self.make_product_line(task)
        _, bom_line = self.make_bom(
            product_line, section_type=BomSectionType.ACCESSORY, budget_quantity="12",
        )
        response = self.create_for_task(task)
        self.assertEqual(response.status_code, 201, response.data)
        return PurchaseOrderLine.objects.get(purchase_order_id=response.data["data"]["id"]), bom_line

    def create_for_task(self, task):
        source = self.get_source(task)
        self.assertEqual(source.status_code, 200, source.data)
        return self.client.post(
            "/api/v1/purchase-orders/",
            self.create_payload(task, source.data["data"], actual_purchase_quantity="12.0000"),
            format="json",
        )

    def make_saved_material(self, number="SAVED-PURCHASE-001", **overrides):
        values = {
            "material_number": number,
            "item_type": "MATERIAL",
            "category": self.inventory_material.category,
            "material_name": "库存原料名称",
            "specification": "已保存规格",
            "unit": self.inventory_material.unit,
            "warehouse_number": "TEST",
            "warehouse_name": "测试仓库",
        }
        values.update(overrides)
        return RawMaterialInformation.objects.create(**values)

    def test_create_saves_raw_material_and_unit_identity(self):
        purchase_line, _ = self.create_material_purchase()
        self.assertEqual(purchase_line.calculation_snapshot, {
            "schema_version": 1,
            "source": "PRODUCTION_PURCHASE",
            "raw_material_id": str(self.inventory_material.pk),
            "unit_id": str(self.inventory_material.unit_id),
        })

    def test_saved_identity_survives_bom_source_change(self):
        purchase_line, bom_line = self.create_material_purchase()
        before = deepcopy(purchase_line.calculation_snapshot)
        self.assertEqual(before.get("raw_material_id"), str(self.inventory_material.pk))
        other = self.make_saved_material()
        bom_line.raw_values = {"source_inventory_material_id": str(other.pk)}
        bom_line.save(update_fields=["raw_values", "updated_at"])
        purchase_line.refresh_from_db()
        self.assertEqual(purchase_line.calculation_snapshot, before)
        from apps.procurement.material_receipt_identity import resolve_purchase_material
        with self.assertNumQueries(1):
            resolved = resolve_purchase_material(purchase_line)
        self.assertEqual(resolved.pk, self.inventory_material.pk)

    def test_missing_bom_identity_does_not_save_partial_purchase(self):
        task = self.make_task("MISSING")
        _, bom_line = self.make_bom(
            self.make_product_line(task),
            section_type=BomSectionType.ACCESSORY, budget_quantity="12",
        )
        source = self.get_source(task)
        self.assertEqual(source.status_code, 200, source.data)
        self.assertTrue(source.data["data"]["can_create"], source.data)
        payload = self.create_payload(task, source.data["data"], actual_purchase_quantity="12.0000")
        bom_line.raw_values = {}
        bom_line.save(update_fields=["raw_values", "updated_at"])
        before = PurchaseOrder.objects.count(), PurchaseOrderLine.objects.count()
        response = self.client.post("/api/v1/purchase-orders/", payload, format="json")
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual((PurchaseOrder.objects.count(), PurchaseOrderLine.objects.count()), before)

    def test_non_material_source_rolls_back_order_and_previous_line(self):
        task = self.make_task("WRONG-TYPE")
        _, first_line = self.make_bom(
            self.make_product_line(task),
            section_type=BomSectionType.ACCESSORY, budget_quantity="12",
        )
        semi_finished = self.make_saved_material(item_type="SEMI_FINISHED")
        BomLine.objects.create(
            section=first_line.section, line_number=2, part_name="不允许采购半成品",
            unit="PCS", budget_quantity="12",
            raw_values={"source_inventory_material_id": str(semi_finished.pk)},
        )
        before = PurchaseOrder.objects.count(), PurchaseOrderLine.objects.count()
        response = self.create_for_task(task)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual((PurchaseOrder.objects.count(), PurchaseOrderLine.objects.count()), before)

    def test_snapshot_builder_rejects_missing_material_source(self):
        from apps.procurement.material_receipt_identity import build_purchase_material_snapshot
        with self.assertRaises(ValidationError):
            build_purchase_material_snapshot(BomLine(raw_values={}))

    def test_legacy_saved_number_resolves_without_bom_or_name_matching(self):
        from apps.procurement.material_receipt_identity import resolve_purchase_material
        material = self.make_saved_material()
        line = PurchaseOrderLine(
            calculation_snapshot={}, raw_material_snapshot=material.material_number,
            part_name_snapshot="和库存名称不同的生产部件",
        )
        with self.assertNumQueries(1):
            resolved = resolve_purchase_material(line)
        self.assertEqual(resolved.pk, material.pk)
        self.assertEqual(resolved.unit_id, material.unit_id)

    def test_legacy_missing_number_rejects_instead_of_matching_material_name(self):
        from apps.procurement.material_receipt_identity import resolve_purchase_material
        material = self.make_saved_material()
        for saved_number in ("", "DOES-NOT-EXIST", material.material_name):
            with self.subTest(saved_number=saved_number):
                with self.assertRaises(Conflict) as raised:
                    resolve_purchase_material(PurchaseOrderLine(
                        calculation_snapshot={}, raw_material_snapshot=saved_number,
                    ))
                self.assertEqual(raised.exception.api_error_code, "PURCHASE_MATERIAL_IDENTITY_MISSING")

    def test_legacy_ambiguous_number_including_archived_row_rejects(self):
        from apps.procurement.material_receipt_identity import resolve_purchase_material
        material = self.make_saved_material(source_row_number=2000000101)
        duplicate = self.make_saved_material(source_row_number=2000000102)
        line = PurchaseOrderLine(calculation_snapshot={}, raw_material_snapshot=material.material_number)
        for archived_at, item_type in ((None, "MATERIAL"), (timezone.now(), "MATERIAL"), (None, "SEMI_FINISHED")):
            duplicate.archived_at = archived_at
            duplicate.item_type = item_type
            duplicate.save(update_fields=["archived_at", "item_type"])
            with self.subTest(archived=bool(archived_at), item_type=item_type), self.assertRaises(Conflict):
                resolve_purchase_material(line)

    def test_legacy_unique_archived_material_rejects(self):
        from apps.procurement.material_receipt_identity import resolve_purchase_material
        material = self.make_saved_material(archived_at=timezone.now())
        with self.assertRaises(Conflict):
            resolve_purchase_material(PurchaseOrderLine(
                calculation_snapshot={}, raw_material_snapshot=material.material_number,
            ))

    def test_explicit_missing_archived_or_non_material_id_never_falls_back_to_number(self):
        from apps.procurement.material_receipt_identity import resolve_purchase_material
        fallback = self.make_saved_material()
        archived = self.make_saved_material("SAVED-ARCHIVED", archived_at=timezone.now())
        semi_finished = self.make_saved_material("SAVED-SEMI", item_type="SEMI_FINISHED")
        for material_id in (uuid4(), archived.pk, semi_finished.pk):
            with self.subTest(material_id=material_id), self.assertRaises(Conflict):
                resolve_purchase_material(PurchaseOrderLine(
                    calculation_snapshot={"raw_material_id": str(material_id)},
                    raw_material_snapshot=fallback.material_number,
                ))

    def test_explicit_material_id_is_uuid_validated_without_reading_number(self):
        from apps.procurement.material_receipt_identity import get_purchase_material_id
        self.assertIsNone(get_purchase_material_id(PurchaseOrderLine(calculation_snapshot={})))
        self.assertEqual(get_purchase_material_id(PurchaseOrderLine(
            calculation_snapshot={"raw_material_id": str(self.inventory_material.pk)},
        )), self.inventory_material.pk)
        for raw_id in (None, "", "broken-id", [str(self.inventory_material.pk)], {"id": str(self.inventory_material.pk)}):
            with self.subTest(raw_id=raw_id), self.assertRaises(Conflict):
                get_purchase_material_id(PurchaseOrderLine(calculation_snapshot={"raw_material_id": raw_id}))
        for snapshot in ([], "invalid-snapshot"):
            with self.subTest(snapshot=snapshot), self.assertRaises(Conflict):
                get_purchase_material_id(PurchaseOrderLine(calculation_snapshot=snapshot))

    def test_saved_unit_change_rejects_material_identity(self):
        from apps.procurement.material_receipt_identity import resolve_purchase_material
        material = self.make_saved_material()
        saved_unit_id = material.unit_id
        other_unit = ProductionUnit.objects.exclude(pk=saved_unit_id).first()
        self.assertIsNotNone(other_unit)
        material.unit = other_unit
        material.save(update_fields=["unit"])
        with self.assertRaises(Conflict):
            resolve_purchase_material(PurchaseOrderLine(calculation_snapshot={
                "raw_material_id": str(material.pk), "unit_id": str(saved_unit_id),
            }))


class SavedPipePurchaseSnapshotTests(APITestCase):
    setUp = pipe_fixture.PipePurchaseOrderApiTests.setUp
    make_task = purchase_fixture.PurchaseOrderApiTests.make_task
    make_product_line = purchase_fixture.PurchaseOrderApiTests.make_product_line
    make_bom = purchase_fixture.PurchaseOrderApiTests.make_bom
    get_source = purchase_fixture.PurchaseOrderApiTests.get_source
    create_payload = staticmethod(purchase_fixture.PurchaseOrderApiTests.create_payload)
    create = pipe_fixture.PipePurchaseOrderApiTests.create

    def test_pipe_calculation_snapshot_is_not_overwritten_by_material_identity(self):
        from apps.procurement.pipe_purchase import pipe_source_snapshot
        self.line.refresh_from_db()
        before = deepcopy(pipe_source_snapshot(self.line))
        response = self.create()
        self.assertEqual(response.status_code, 201, response.data)
        line = PurchaseOrderLine.objects.get(purchase_order_id=response.data["data"]["id"])
        self.assertEqual(line.calculation_snapshot, before)
        self.assertIn("suggested_bar_count", line.calculation_snapshot)
