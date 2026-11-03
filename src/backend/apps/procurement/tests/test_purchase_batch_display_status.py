from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase

from apps.procurement.api.group_serializers import PurchaseBatchSummarySerializer
from apps.procurement.api.read_details import PurchaseOrderReadDetailSerializer
from apps.procurement.api.serializers import PurchaseOrderDetailSerializer
from apps.procurement.group_selectors import purchase_batch_display_status
from apps.procurement.models import PurchaseReturnLine


def related(items):
    return SimpleNamespace(all=lambda: items)


class MissingReturn(SimpleNamespace):
    @property
    def purchase_return_line(self):
        raise PurchaseReturnLine.DoesNotExist


class PurchaseBatchDisplayStatusTests(SimpleTestCase):
    def setUp(self):
        self.material_id = uuid4()
        self.lines = []
        order_id = uuid4()
        self.order = SimpleNamespace(
            pk=order_id, id=order_id, purchase_group_id=uuid4(), status="PURCHASING", lines=related(self.lines),
            order_number="CGDD-TEST", batch_number=1, batch_type="NORMAL", currency_code_snapshot="CNY",
            total_amount=Decimal("100"), completed_at=None, completed_by_employee_id=None, completion_remark="",
        )

    def line(self, actual="100"):
        line = SimpleNamespace(
            pk=uuid4(), actual_purchase_quantity=Decimal(actual) if actual is not None else None,
            calculation_snapshot={"raw_material_id": str(self.material_id)}, source_unit_text="米",
            material_catalog_id=None, material_selection_snapshot={}, section_type_snapshot="PROFILE",
            actual_bar_count=None, material_inbound_lines=related([]),
        )
        self.lines.append(line)
        return line

    def inbound(self, accepted="100", *, returned="0", status="CONFIRMED"):
        inbound_id = uuid4()
        return SimpleNamespace(
            inbound_id=inbound_id, inbound=SimpleNamespace(pk=inbound_id, status=status, purchase_order_id=self.order.pk),
            source_unit_text_snapshot="米", raw_material_information_id=self.material_id,
            material_catalog_id=None, material_selection_snapshot={},
            accepted_quantity=Decimal(accepted), return_quantity=Decimal(returned), accepted_bar_count=None,
            purchase_return_line=None,
        )

    def add_return(self, inbound, status="COMPLETED"):
        inbound.purchase_return_line = SimpleNamespace(
            quantity=inbound.return_quantity,
            return_order=SimpleNamespace(status=status, purchase_order_id=self.order.pk, inbound_id=inbound.inbound_id),
        )
        return inbound.purchase_return_line

    def test_all_lines_use_actual_quantity_and_accumulate_confirmed_receipts(self):
        self.line().material_inbound_lines = related([self.inbound("30"), self.inbound("70")])
        self.line("50").material_inbound_lines = related([self.inbound("50")])
        for status in ("PURCHASING", "SUBMITTED"):
            self.order.status = status
            self.assertEqual(purchase_batch_display_status(self.order), "COMPLETED")
            self.assertEqual(self.order.status, status)
            self.assertIsNone(self.order.completed_at)
            self.assertIsNone(self.order.completed_by_employee_id)
            self.assertEqual(self.order.completion_remark, "")

    def test_one_line_over_received_cannot_cover_another_short_line(self):
        self.line().material_inbound_lines = related([self.inbound("150")])
        self.line().material_inbound_lines = related([self.inbound("50")])
        self.assertEqual(purchase_batch_display_status(self.order), "PURCHASING")

    def test_pending_quality_blocks_even_when_confirmed_quantity_is_enough(self):
        self.line().material_inbound_lines = related([self.inbound("110"), self.inbound("10", status="PENDING_QUALITY")])
        self.assertEqual(purchase_batch_display_status(self.order), "PURCHASING")

    def test_empty_batch_missing_receipts_or_invalid_actual_quantity_stay_uncompleted(self):
        self.assertEqual(purchase_batch_display_status(self.order), "PURCHASING")
        line = self.line()
        self.assertEqual(purchase_batch_display_status(self.order), "PURCHASING")
        line.material_inbound_lines = related([self.inbound()])
        for actual in (None, Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity")):
            with self.subTest(actual=actual):
                line.actual_purchase_quantity = actual
                self.assertEqual(purchase_batch_display_status(self.order), "PURCHASING")

    def test_manual_completed_draft_and_non_batch_statuses_are_preserved_without_loading_lines(self):
        self.order.lines = None
        for status, group_id in [("COMPLETED", uuid4()), ("DRAFT", uuid4()), ("PURCHASING", None)]:
            self.order.status, self.order.purchase_group_id = status, group_id
            self.assertEqual(purchase_batch_display_status(self.order), status)

    def test_missing_root_counts_do_not_change_meter_based_completion(self):
        self.line().material_inbound_lines = related([self.inbound()])
        self.assertEqual(purchase_batch_display_status(self.order), "COMPLETED")

    def test_unknown_legacy_identity_or_unit_blocks_completion(self):
        line = self.line()
        line.material_inbound_lines = related([self.inbound()])
        for field, value in [("calculation_snapshot", {}), ("calculation_snapshot", []),
                             ("source_unit_text", ""), ("source_unit_text", " ")]:
            with self.subTest(field=field, value=value):
                original = getattr(line, field)
                setattr(line, field, value)
                self.assertEqual(purchase_batch_display_status(self.order), "PURCHASING")
                setattr(line, field, original)

    def test_inbound_identity_unit_or_parent_mismatch_blocks_completion(self):
        line = self.line()
        inbound = self.inbound()
        for field, value in [("raw_material_information_id", None), ("raw_material_information_id", uuid4()),
                             ("source_unit_text_snapshot", "根"), ("material_catalog_id", uuid4())]:
            with self.subTest(field=field):
                changed = deepcopy(inbound)
                setattr(changed, field, value)
                line.material_inbound_lines = related([changed])
                self.assertEqual(purchase_batch_display_status(self.order), "PURCHASING")
        inbound.inbound.purchase_order_id = uuid4()
        line.material_inbound_lines = related([inbound])
        self.assertEqual(purchase_batch_display_status(self.order), "PURCHASING")

    def test_invalid_inbound_numbers_never_display_completed(self):
        line = self.line()
        for field in ("accepted_quantity", "return_quantity"):
            for value in (None, Decimal("-1"), Decimal("NaN"), Decimal("Infinity")):
                with self.subTest(field=field, value=value):
                    inbound = self.inbound()
                    setattr(inbound, field, value)
                    line.material_inbound_lines = related([inbound])
                    self.assertEqual(purchase_batch_display_status(self.order), "PURCHASING")

    def test_pending_or_missing_returns_block_even_after_full_accepted_quantity(self):
        line = self.line()
        inbound = self.inbound(returned="20")
        line.material_inbound_lines = related([inbound])
        self.assertEqual(purchase_batch_display_status(self.order), "PURCHASING")
        for status in ("QUALITY_GENERATED", "PROCUREMENT_CONFIRMED"):
            self.add_return(inbound, status)
            self.assertEqual(purchase_batch_display_status(self.order), "PURCHASING")
        self.add_return(inbound)
        self.assertEqual(purchase_batch_display_status(self.order), "COMPLETED")

    def test_completed_return_quantity_does_not_replace_accepted_quantity(self):
        line = self.line()
        inbound = self.inbound("80", returned="20")
        self.add_return(inbound)
        receipts = [inbound]
        line.material_inbound_lines = related(receipts)
        self.assertEqual(purchase_batch_display_status(self.order), "PURCHASING")
        receipts.append(self.inbound("20"))
        self.assertEqual(purchase_batch_display_status(self.order), "COMPLETED")

    def test_return_quantity_or_source_mismatch_blocks_completion(self):
        line = self.line()
        inbound = self.inbound(returned="20")
        record = self.add_return(inbound)
        line.material_inbound_lines = related([inbound])
        record.quantity = Decimal("10")
        self.assertEqual(purchase_batch_display_status(self.order), "PURCHASING")
        record.quantity = Decimal("20")
        record.return_order.purchase_order_id = uuid4()
        self.assertEqual(purchase_batch_display_status(self.order), "PURCHASING")
        record.return_order.purchase_order_id = self.order.pk
        record.return_order.inbound_id = uuid4()
        self.assertEqual(purchase_batch_display_status(self.order), "PURCHASING")

    def test_missing_reverse_return_relation_is_handled_narrowly(self):
        values = vars(self.inbound()).copy()
        values.pop("purchase_return_line")
        inbound = MissingReturn(**values)
        self.line().material_inbound_lines = related([inbound])
        self.assertEqual(purchase_batch_display_status(self.order), "COMPLETED")
        inbound.return_quantity = Decimal("1")
        self.assertEqual(purchase_batch_display_status(self.order), "PURCHASING")

    def catalog_line(self):
        line = self.line()
        catalog_id = uuid4()
        selected = {"schema_version": 1, "catalog_id": str(catalog_id), "catalog_version": "saved-version",
                    "category_key": "TUBE", "template_key": "TUBE", "name": "保存管材", "scope": "BASE",
                    "processing_state": "RAW", "processing_stage": "RAW", "completed_craft": None, "semi_kind": None,
                    "attributes": {"material": "铁", "shape": "圆管", "section_size": "20", "thickness": "1"},
                    "unit_id": str(uuid4()), "unit_name": "根", "display_name": "保存管材 / 根"}
        line.material_catalog_id, line.material_selection_snapshot = catalog_id, selected
        line.calculation_snapshot = {"material_catalog_id": str(catalog_id)}
        inbound = self.inbound()
        inbound.raw_material_information_id = None
        inbound.material_catalog_id, inbound.material_selection_snapshot = catalog_id, deepcopy(selected)
        line.material_inbound_lines = related([inbound])
        return line, inbound

    def test_catalog_identity_completes_without_legacy_raw_material_id(self):
        line, inbound = self.catalog_line()
        before = deepcopy(line.material_selection_snapshot)
        self.assertEqual(purchase_batch_display_status(self.order), "COMPLETED")
        self.assertEqual(line.material_selection_snapshot, before)
        self.assertEqual(inbound.material_selection_snapshot, before)

    def test_catalog_mismatch_or_invalid_saved_selection_stays_uncompleted(self):
        line, inbound = self.catalog_line()
        inbound.material_catalog_id = uuid4()
        self.assertEqual(purchase_batch_display_status(self.order), "PURCHASING")
        inbound.material_catalog_id = line.material_catalog_id
        inbound.material_selection_snapshot["attributes"]["thickness"] = "2"
        self.assertEqual(purchase_batch_display_status(self.order), "PURCHASING")
        inbound.material_selection_snapshot = deepcopy(line.material_selection_snapshot)
        line.material_selection_snapshot["catalog_id"] = str(uuid4())
        self.assertEqual(purchase_batch_display_status(self.order), "PURCHASING")

    def test_both_read_serializers_share_display_contract_without_changing_behavior_serializer(self):
        self.line().material_inbound_lines = related([self.inbound()])
        summary = PurchaseBatchSummarySerializer(self.order).data
        self.assertEqual((summary["status"], summary["display_status"]), ("PURCHASING", "COMPLETED"))
        for serializer in (PurchaseBatchSummarySerializer(), PurchaseOrderReadDetailSerializer()):
            field = serializer.fields["display_status"]
            self.assertTrue(field.read_only)
            self.assertEqual(field.to_representation(self.order), "COMPLETED")
        self.assertIn("display_status", PurchaseOrderReadDetailSerializer.Meta.fields)
        self.assertNotIn("display_status", PurchaseOrderDetailSerializer().fields)
