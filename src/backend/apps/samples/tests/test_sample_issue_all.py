"""整单领料定向测试；所有前置单据只写入 Django 独占测试库。"""

from decimal import Decimal
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.inventory.models import MaterialInbound, MaterialInboundLine, MaterialStockBalance, MaterialStockMovement, PublicStockBalance, PublicStockMovement, WarehouseZone
from apps.inventory.pipe_stock_services import credit_pipe_inbound
from apps.inventory.public_stock_identity import build_pipe_stock_identity
from apps.inventory.stock_services import credit_confirmed_inbound_line
from apps.procurement.tests import test_sample_pipe_flow as pipe_fixture
from apps.procurement.tests import test_sample_purchase_api as material_fixture
from apps.reference_data.models import ProductionUnit
from apps.samples.models import SampleMaterialArrival, SampleMaterialIssue


class AllIssueApiHelpers:
    def grant_permissions(self):
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label="samples"))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.issue_url = f"/api/v1/sample-requests/{self.sample.pk}/material-issue/"

    def set_demand(self, need, supply):
        self.demand.update(quantity=str(need), supplyQuantity=str(supply), shortageQuantity=str(Decimal(need) - Decimal(supply)))
        self.procurement.lines = [self.demand]
        self.procurement.save(update_fields=["lines"])
        record = self.procurement.material_request
        record.draft = {"lines": [self.demand], "notes": ""}
        record.warehouse_draft = {"lines": [{"key": self.key, "supplyQuantity": str(supply)}], "notes": ""}
        record.save(update_fields=["draft", "warehouse_draft"])

    def initiate(self):
        current = self.client.get(self.issue_url)
        self.assertEqual(current.status_code, 200, current.data)
        response = self.client.post(self.issue_url + "initiate/", {"client_request_id": str(uuid.uuid4())},
                                    format="json", HTTP_IF_MATCH=current["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def confirm(self, state, request_id=None, **extra):
        return self.client.post(self.issue_url + "confirm/", {"request_id": request_id or str(uuid.uuid4()), **extra},
                                format="json", HTTP_IF_MATCH=state["ETag"])


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
class SampleAllPipeIssueTests(AllIssueApiHelpers, APITestCase):
    def setUp(self):
        pipe_fixture.SamplePipeFlowTests.setUp(self)
        self.grant_permissions()
        ProductionUnit.objects.get_or_create(unit_name="米", defaults={"unit_code": "ALL-ISSUE-M"})
        self.demand.pop("cuttingLengthMm", None)
        self.demand.pop("piecesPerBar", None)
        self.demand.update(pipeInputMode="TOTAL_METERS", unitLabel="米")
        self.set_demand("8", "0")

    def stock(self, bars, *, length="6", arrival=False, zone_id=None, public=True):
        meters = Decimal(length) * bars
        inbound = MaterialInbound.objects.create(
            inbound_number=f"QA-ALL-{uuid.uuid4().hex[:12]}", status="CONFIRMED",
            stock_mode="PUBLIC_V2" if public else "LEGACY", received_by_employee=self.employee,
        )
        identity = build_pipe_stock_identity(raw_material=self.raw_material, raw_bar_length_m=length, unit=self.raw_material.unit)
        identity["raw_bar_length_m"] = str(identity["raw_bar_length_m"])
        line = MaterialInboundLine.objects.create(
            inbound=inbound, raw_material_information=self.raw_material,
            zone_id=zone_id or self.zone_id, measurement_kind="PIPE", raw_bar_length_m=Decimal(length),
            received_bar_count=bars, accepted_bar_count=bars, return_bar_count=0,
            received_quantity=meters, accepted_quantity=meters, return_quantity=0,
            purchased_quantity_snapshot=meters, source_unit_text_snapshot="米",
            calculation_snapshot={"public_stock_identity": identity},
        )
        movement = credit_pipe_inbound(inbound_line_id=line.pk, actor_employee=self.employee)
        if arrival:
            SampleMaterialArrival.objects.create(procurement_request=self.procurement, line_key=self.key,
                                                 inbound_line=line, accepted_quantity=meters)
        return movement.balance

    def test_purchase_roots_above_demand_are_all_issued_without_other_stock(self):
        balance = self.stock(2, arrival=True)
        self.stock(5)
        started = self.initiate()
        row = started.data["data"]["lines"][0]
        self.assertEqual(Decimal(row["availableQuantity"]), Decimal("12"))
        self.assertEqual(row["barCount"], 2)
        self.assertEqual(Decimal(row["procurementQuantity"]), Decimal("8"))
        request_id = str(uuid.uuid4())
        result = self.confirm(started, request_id)
        self.assertEqual(result.status_code, 200, result.data)
        balance.refresh_from_db()
        self.assertEqual((balance.quantity, balance.meter_quantity), (5, Decimal("30")))
        line = SampleMaterialIssue.objects.get().lines.get()
        self.assertEqual((line.requested_quantity, line.available_quantity, line.issued_quantity), (8, 12, 12))
        self.assertEqual(result.data["data"]["lines"][0]["barCount"], 2)
        replay = self.confirm(result, request_id)
        self.assertEqual(replay.status_code, 200, replay.data)
        replay_original = self.confirm(started, request_id)
        self.assertEqual(replay_original.status_code, 200, replay_original.data)
        duplicate = self.confirm(result)
        self.assertEqual(duplicate.status_code, 409, duplicate.data)
        self.assertEqual(PublicStockMovement.objects.filter(source_type="SAMPLE_MATERIAL_ISSUE").count(), 1)
        self.assertFalse(MaterialStockMovement.objects.filter(source_type="SAMPLE_MATERIAL_ISSUE").exists())

    def test_existing_supply_and_arrival_share_balance_without_double_counting(self):
        self.set_demand("14", "6")
        balance = self.stock(2)
        self.stock(2, arrival=True)
        started = self.initiate()
        self.assertEqual(started.data["data"]["lines"][0]["barCount"], 3)
        result = self.confirm(started)
        self.assertEqual(result.status_code, 200, result.data)
        balance.refresh_from_db()
        self.assertEqual((balance.quantity, balance.meter_quantity), (1, Decimal("6")))
        self.assertEqual(SampleMaterialIssue.objects.get().lines.get().issued_quantity, 18)

    def test_public_cross_zone_supply_is_fully_debited(self):
        self.set_demand("12", "12")
        first = self.stock(1)
        zone = WarehouseZone.objects.create(warehouse=first.zone.warehouse, zone_name="整单领料二区")
        second = self.stock(1, zone_id=zone.pk)
        started = self.initiate()
        self.assertEqual(len(started.data["data"]["lines"][0]["pipeBatches"]), 2)
        result = self.confirm(started)
        self.assertEqual(result.status_code, 200, result.data)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.quantity, second.quantity), (0, 0))
        self.assertEqual(PublicStockMovement.objects.filter(source_type="SAMPLE_MATERIAL_ISSUE").count(), 2)

    @override_settings(PUBLIC_STOCK_FLOW_ENABLED=False)
    def test_legacy_cross_zone_supply_is_fully_debited(self):
        self.set_demand("12", "12")
        first = self.stock(1, public=False)
        zone = WarehouseZone.objects.create(warehouse=first.zone.warehouse, zone_name="旧账整单领料二区")
        second = self.stock(1, zone_id=zone.pk, public=False)
        result = self.confirm(self.initiate())
        self.assertEqual(result.status_code, 200, result.data)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.quantity, second.quantity), (0, 0))
        self.assertEqual(MaterialStockMovement.objects.filter(source_type="SAMPLE_MATERIAL_ISSUE").count(), 2)
        self.assertFalse(PublicStockMovement.objects.filter(source_type="SAMPLE_MATERIAL_ISSUE").exists())

    def test_inexact_supply_does_not_round_or_partially_debit(self):
        self.set_demand("8", "8")
        balance = self.stock(2)
        started = self.initiate()
        self.assertFalse(started.data["data"]["canConfirm"])
        self.assertTrue(started.data["data"]["blockers"])
        result = self.confirm(started)
        self.assertEqual(result.status_code, 409, result.data)
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 2)
        self.assertFalse(PublicStockMovement.objects.filter(source_type="SAMPLE_MATERIAL_ISSUE").exists())

    def test_changed_stock_etag_rejects_stale_preview(self):
        self.stock(2, arrival=True)
        started = self.initiate()
        self.stock(1)
        stale = self.confirm(started)
        self.assertEqual(stale.status_code, 412, stale.data)
        self.assertFalse(PublicStockMovement.objects.filter(source_type="SAMPLE_MATERIAL_ISSUE").exists())
        fresh = self.client.get(self.issue_url)
        self.assertEqual(self.confirm(fresh).status_code, 200)

    def test_new_arrival_after_initiation_requires_fresh_preview(self):
        self.stock(1, arrival=True)
        started = self.initiate()
        self.stock(1, arrival=True)
        # 真实到货服务会更新主单时间；夹具同样记录来源变化。
        self.sample.save(update_fields=["updated_at"])
        stale = self.confirm(started)
        self.assertEqual(stale.status_code, 412, stale.data)
        fresh = self.client.get(self.issue_url)
        self.assertEqual(fresh.data["data"]["lines"][0]["barCount"], 2)
        result = self.confirm(fresh)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(SampleMaterialIssue.objects.get().lines.get().issued_quantity, 12)

    def test_client_quantities_are_rejected_and_missing_etag_is_required(self):
        self.stock(2, arrival=True)
        started = self.initiate()
        changed = self.confirm(started, lines=[{"line_id": started.data["data"]["lines"][0]["id"], "issued_quantity": "1"}])
        self.assertEqual(changed.status_code, 400, changed.data)
        missing = self.client.post(self.issue_url + "confirm/", {"request_id": str(uuid.uuid4())}, format="json")
        self.assertEqual(missing.status_code, 428, missing.data)
        self.assertFalse(PublicStockMovement.objects.filter(source_type="SAMPLE_MATERIAL_ISSUE").exists())

    def test_mixed_lengths_can_be_issued_when_allocated_meters_match(self):
        self.set_demand("10", "10")
        first = self.stock(1, length="6")
        second = self.stock(1, length="4")
        started = self.initiate()
        self.assertEqual(started.data["data"]["lines"][0]["barCount"], 2)
        result = self.confirm(started)
        self.assertEqual(result.status_code, 200, result.data)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.quantity, second.quantity), (0, 0))

    def test_exact_shorter_roots_are_selected_instead_of_greedy_partial_issue(self):
        self.set_demand("8", "8")
        first = self.stock(1, length="6")
        zone = WarehouseZone.objects.create(id=uuid.UUID(int=2**128 - 1), warehouse=first.zone.warehouse, zone_name="4米库区")
        second = self.stock(2, length="4", zone_id=zone.pk)
        started = self.initiate()
        self.assertTrue(started.data["data"]["canConfirm"])
        result = self.confirm(started)
        self.assertEqual(result.status_code, 200, result.data)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.quantity, second.quantity), (1, 0))

    def test_earlier_supply_line_does_not_consume_later_lines_arrival_budget(self):
        # 同种材料两需求行：第一行领核库现货，第二行领自己的到货。
        self.key = str(uuid.UUID(int=2))
        self.demand["key"] = self.key
        self.set_demand("6", "0")
        purchased = self.stock(1, arrival=True)
        zone = WarehouseZone.objects.create(id=uuid.UUID(int=2**128 - 1), warehouse=purchased.zone.warehouse, zone_name="额外现货区")
        existing = self.stock(1, zone_id=zone.pk)
        first_key = str(uuid.UUID(int=1))
        first_row = {**self.demand, "key": first_key}
        record = self.procurement.material_request
        record.draft["lines"].insert(0, first_row)
        record.warehouse_draft["lines"].insert(0, {"key": first_key, "supplyQuantity": "6"})
        record.save(update_fields=["draft", "warehouse_draft"])
        result = self.confirm(self.initiate())
        self.assertEqual(result.status_code, 200, result.data)
        purchased.refresh_from_db()
        existing.refresh_from_db()
        self.assertEqual((purchased.quantity, existing.quantity), (0, 0))
        self.assertEqual(list(SampleMaterialIssue.objects.get().lines.values_list("issued_quantity", flat=True)), [6, 6])

    def test_failure_of_later_material_rolls_back_pipe_debit_and_issue_status(self):
        from apps.products.models import RawMaterialInformation
        from apps.reference_data.models import ProductCategory
        balance = self.stock(2, arrival=True)
        category, _ = ProductCategory.objects.get_or_create(category_name="五金", defaults={"item_type": "MATERIAL"})
        material = RawMaterialInformation.objects.create(
            material_number="QA-ALL-NO-STOCK", item_type="MATERIAL", category=category,
            material_name="事务回滚五金", specification="M6", material="钢", unit=self.raw_material.unit,
        )
        other = {**self.demand, "key": str(uuid.uuid4()), "category": "hardware", "rawMaterialId": str(material.pk),
                 "name": material.material_name, "quantity": "1", "unitLabel": "根"}
        record = self.procurement.material_request
        record.draft["lines"].append(other)
        record.warehouse_draft["lines"].append({"key": other["key"], "supplyQuantity": "1"})
        record.save(update_fields=["draft", "warehouse_draft"])
        started = self.initiate()
        # 固定测试夹具行顺序，确保先扣管材，再因五金不足失败。
        SampleMaterialIssue.objects.get().lines.filter(category="tube").update(id=uuid.UUID(int=1))
        SampleMaterialIssue.objects.get().lines.filter(category="hardware").update(id=uuid.UUID(int=2))
        result = self.confirm(started)
        self.assertEqual(result.status_code, 400, result.data)
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 2)
        self.assertEqual(SampleMaterialIssue.objects.get().status, "PENDING_CONFIRMATION")
        self.assertFalse(SampleMaterialIssue.objects.get().lines.exclude(issued_quantity=None).exists())
        self.assertFalse(PublicStockMovement.objects.filter(source_type="SAMPLE_MATERIAL_ISSUE").exists())


class SampleAllOtherMaterialIssueTests(AllIssueApiHelpers, APITestCase):
    def setUp(self):
        material_fixture.SamplePurchaseApiTests.setUp(self)
        self.grant_permissions()
        self.set_demand("4", "2")

    def test_non_pipe_supply_plus_actual_arrival_are_all_issued(self):
        from apps.inventory.stock_services import credit_material_stock
        credit_material_stock(raw_material=self.raw_material, unit=self.raw_material.unit,
                              zone=WarehouseZone.objects.get(pk=self.zone_id), quantity=7,
                              source_type="QA_OPENING", source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
                              actor_employee=self.employee)
        inbound = MaterialInbound.objects.create(inbound_number="QA-ALL-OTHER", status="CONFIRMED",
                                                received_by_employee=self.employee)
        line = MaterialInboundLine.objects.create(inbound=inbound, raw_material_information=self.raw_material,
                                                  zone_id=self.zone_id, received_quantity=3, accepted_quantity=3,
                                                  return_quantity=0, purchased_quantity_snapshot=3,
                                                  source_unit_text_snapshot=self.raw_material.unit.unit_name)
        credit_confirmed_inbound_line(line=line, actor_employee=self.employee)
        SampleMaterialArrival.objects.create(procurement_request=self.procurement, line_key=self.key,
                                             inbound_line=line, accepted_quantity=3)
        result = self.confirm(self.initiate())
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(SampleMaterialIssue.objects.get().lines.get().issued_quantity, 5)
        self.assertEqual(MaterialStockBalance.objects.get(raw_material=self.raw_material).quantity, 5)
