import copy
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError as ModelValidationError
from django.db import DatabaseError, transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.core.api.exceptions import Conflict
from apps.inventory.models import PublicStockMovement, SemiFinishedStockMovement
from apps.inventory.public_bom_snapshot import build_output_identity, freeze_bom_line
from apps.outsourcing.models import OutsourcingOrder, OutsourcingProcessingItem
from apps.reference_data.models import TubeCoatingColor

from ..legacy_public_transition import apply_legacy_public_transition, evidence_digest, preview_legacy_public_transition
from ..models import MetalProcessingExternalOrder, MetalProcessingOriginalHandoff, OriginalHandoffPublicTransition
from .test_metal_processing_p4 import MetalProcessingP4Fixture


class LegacyPublicTransitionTests(MetalProcessingP4Fixture, APITestCase):
    def setUp(self):
        super().setUp()
        self.handoff = self.create_original_handoff(8)
        self.manifest = self.make_manifest()

    def make_manifest(self):
        handoff = self.handoff
        source = handoff.source
        conversion = source.source_snapshot["conversion_snapshot"]
        item = OutsourcingProcessingItem.objects.select_related("unit").get(order_product__order_id=self.original_order)
        color = TubeCoatingColor.objects.create(color_name="黑色磨砂接续测试")
        old = {"id": conversion["bom_line_id"], "category": "管材", "part_name": conversion["part_name"],
            "material": "铁", "specification": self.line.specification_snapshot, "unit": "根", "hardness": "",
            "raw_values": {"tube_shape": "矩形管", "tube_diameter": "20*28", "tube_thickness": "0.8", "tube_coating_color": "/"},
            **{key: conversion[key] for key in ("cutting_length_mm", "pieces_per_bar", "raw_bar_length_m", "component_identity")}}
        audit = AuditLog.objects.create(object_type="BOM", object_id=conversion["bom_id"], action="SIMULATION_SUPPLEMENT",
            after_data={"lines": [old]}, occurred_at=self.line.issue.issued_at - timedelta(microseconds=2))
        # 测试夹具明确提供当时实际入库的物理属性，不能靠当前材料档案补历史。
        inbound = self.line.batch_allocations.get().inbound_line
        for field in ("category", "material", "part_name", "specification"):
            setattr(inbound, field + "_snapshot", old[field])
        inbound.calculation_snapshot = {key: value for key, value in conversion.items()
            if key not in {"kind", "part_name", "source_revision_hash"}}
        inbound.save(update_fields=["category_snapshot", "material_snapshot", "part_name_snapshot", "specification_snapshot", "calculation_snapshot", "updated_at"])
        line = SimpleNamespace(pk=conversion["bom_line_id"],
            section=SimpleNamespace(section_type="PROFILE", title="型材", bom_id=conversion["bom_id"]),
            **{key: old[key] for key in ("category", "part_name", "material", "specification", "unit", "hardness", "cutting_length_mm")},
            cutting_pieces_per_set=None, raw_values={**old["raw_values"], "tube_coating_color": color.color_name})
        frozen = freeze_bom_line(line)
        identity = build_output_identity(frozen, handoff.original_order.craft, item.unit)
        candidate = {"issue_line_id": str(self.line.pk), "source_id": str(source.pk), "source_hash": source.source_hash,
            "bom_line_id": conversion["bom_line_id"], "component_identity": conversion["component_identity"],
            "material_number": self.line.material_number_snapshot, "processing_item_id": str(item.pk),
            "original_handoff_id": str(handoff.pk), "original_handoff_snapshot_hash": evidence_digest(handoff.snapshot),
            "original_conversion_hash": evidence_digest(conversion), "historical_audit_id": str(audit.pk),
            "historical_line_path": "after.lines[0]", "historical_line_hash": evidence_digest(old), "historical_color": "/",
            "selected_color": color.color_name, "color_origin": "USER_DELEGATED_SELECTION_TEST",
            "issued_pieces": source.issued_pieces, "completed_pieces": source.completed_pieces,
            "handoff_pieces": handoff.handoff_pieces, "original_deducted_roots": source.source_snapshot["bar_count"],
            "original_deducted_meters": source.source_snapshot["meters"],
            "frozen_candidate": frozen, "candidate_output_identity": identity}
        return {"schema_version": 1, "order_id": str(handoff.original_order_id), "issue_id": str(self.line.issue_id),
            "order_number": handoff.original_order.order_number, "selected_color": {"id": str(color.pk), "name": color.color_name},
            "user_instruction": "五项同色，由操作人选择现有颜色", "authorization_scope": "仅本测试旧原单",
            "color_is_newly_selected_not_historical_evidence": True, "candidate_count": 1, "unique_identity_count": 1,
            "handoff_total_pieces": 8, "original_deducted_roots": source.source_snapshot["bar_count"],
            "original_deducted_meters": source.source_snapshot["meters"],
            "candidate_manifest_sha256": evidence_digest([candidate]), "candidates": [candidate]}

    def adopt(self, *, manifest=None, request_id=None, expected=None):
        manifest = manifest or self.manifest
        receipt = preview_legacy_public_transition(manifest)
        # 维护期总锁、目标白名单由 cutover 专项测试覆盖；此处只隔离其环境前置条件。
        with patch("apps.inventory.public_stock_cutover.require_transition_maintenance") as guard:
            result = apply_legacy_public_transition(manifest=manifest, actor=self.f.employee,
                request_id=request_id or uuid.uuid4(), expected_manifest_hash=expected or receipt["manifest_hash"])
            guard.assert_called_once_with()
        return result

    def add_summary_gap(self):
        return AuditLog.objects.create(object_type="BOM", object_id=self.line.conversion_snapshot["bom_id"], action="UPDATE",
            before_data={"line_count": 5}, after_data={"line_count": 5},
            occurred_at=self.line.issue.issued_at - timedelta(microseconds=1))

    def with_confirmation(self, manifest=None):
        manifest = copy.deepcopy(manifest or self.manifest)
        items = []
        for candidate in manifest["candidates"]:
            line = candidate["frozen_candidate"]["line"]
            items.append({"original_handoff_id": candidate["original_handoff_id"], "source_id": candidate["source_id"],
                "issued_bom_line_id": candidate["bom_line_id"], "cutting_length_mm": line["cutting_length_mm"],
                "material": line["material"], **{key: line["raw_values"][key] for key in ("tube_shape", "tube_diameter", "tube_thickness")}})
        manifest["supplemental_confirmation"] = {"schema_version": 1, "confirmation_id": str(uuid.uuid4()),
            "recorded_at": timezone.now().isoformat(), "confirmed_on": timezone.localdate().isoformat(),
            "confirmed": True, "user_answer": "A", "question": "是否确认这些已领料交接管件的材质、管形、壁厚、截面及切割长度？",
            "statement": "本次补充确认，不宣称旧审计完整", "confirms_current_physical_attributes_not_historical_fact": True,
            "scope": {key: manifest[key] for key in ("issue_id", "order_id", "candidate_manifest_sha256")}, "items": items}
        manifest["supplemental_confirmation_sha256"] = evidence_digest(manifest["supplemental_confirmation"])
        return manifest

    def context(self):
        result = self.client.get(f"/api/v1/metal-processing-handoffs/{self.handoff.pk}/")
        self.assertEqual(result.status_code, 200, result.data)
        return result.data["data"]["good_return_context"]

    def good_payload(self, pieces=3, **extra):
        return {"request_id": str(uuid.uuid4()), "good_pieces": pieces, "zone_id": str(self.f.semi_zone.pk),
            "received_by_employee_id": str(self.f.employee.pk), "return_date": str(timezone.localdate()),
            "remark": "接续原单合格回货", **extra}

    def good_return(self, payload, expected=200, etag=None):
        return self.post(f"/api/v1/metal-processing-handoffs/{self.handoff.pk}/good-returns/", payload,
            expected=expected, etag=etag or self.context()["etag"])

    def test_adoption_readonly_preview_zero_stock_and_immutable_evidence(self):
        before = self.unchanged_ledgers()
        receipt = preview_legacy_public_transition(self.manifest)
        self.assertFalse(OriginalHandoffPublicTransition.objects.exists())
        request_id = uuid.uuid4()
        applied = self.adopt(request_id=request_id, expected=receipt["manifest_hash"])
        replay = self.adopt(request_id=request_id, expected=receipt["manifest_hash"])
        self.assertFalse(applied["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(OriginalHandoffPublicTransition.objects.count(), 1)
        self.assertFalse(PublicStockMovement.objects.exists())
        self.assertEqual(before, self.unchanged_ledgers())
        record = OriginalHandoffPublicTransition.objects.get()
        self.assertEqual(record.evidence["historical_line"]["raw_values"]["tube_coating_color"], "/")
        self.assertEqual(record.public_identity["identity_snapshot"]["color"], "黑色磨砂接续测试")
        audit = AuditLog.objects.get(object_id=record.pk, action="ADOPTED")
        self.assertEqual(audit.request_id, request_id)
        with self.assertRaises(ModelValidationError):
            record.save()
        with self.assertRaises(DatabaseError), transaction.atomic():
            OriginalHandoffPublicTransition.objects.filter(pk=record.pk).update(source_hash="f" * 64)
        with self.assertRaises(DatabaseError), transaction.atomic():
            OriginalHandoffPublicTransition.objects.filter(pk=record.pk).delete()
        with self.assertRaises(Conflict):
            self.adopt()

    def test_reject_stale_digest_and_changed_historical_identity(self):
        with self.assertRaises(Conflict):
            self.adopt(expected="0" * 64)
        altered = copy.deepcopy(self.manifest)
        altered["candidates"][0]["frozen_candidate"]["line"]["raw_values"]["tube_thickness"] = "8"
        altered["candidate_manifest_sha256"] = evidence_digest(altered["candidates"])
        with self.assertRaises(ValidationError):
            preview_legacy_public_transition(altered)
        self.assertFalse(OriginalHandoffPublicTransition.objects.exists())

    def test_formal_adoption_requires_active_administrator_employee(self):
        self.f.user.is_superuser = False
        self.f.user.save(update_fields=["is_superuser"])
        with self.assertRaises(ValidationError):
            self.adopt()
        self.assertFalse(OriginalHandoffPublicTransition.objects.exists())
        self.assertFalse(PublicStockMovement.objects.exists())

    def test_same_geometry_later_material_change_rejects_earlier_historical_identity(self):
        original_audit = AuditLog.objects.get(pk=self.manifest["candidates"][0]["historical_audit_id"])
        newer_line = {**original_audit.after_data["lines"][0], "material": "铝"}
        AuditLog.objects.create(object_type="BOM", object_id=original_audit.object_id, action="UPDATE",
            before_data=original_audit.after_data, after_data={"lines": [newer_line]},
            occurred_at=self.line.issue.issued_at - timedelta(microseconds=1))
        with self.assertRaisesMessage(ValidationError, "实物属性已经变化"):
            preview_legacy_public_transition(self.manifest)
        self.assertFalse(OriginalHandoffPublicTransition.objects.exists())
        self.assertFalse(PublicStockMovement.objects.exists())

    def test_intervening_summary_only_bom_change_cannot_prove_unchanged_identity(self):
        AuditLog.objects.create(object_type="BOM", object_id=self.line.conversion_snapshot["bom_id"], action="UPDATE",
            before_data={"line_count": 5}, after_data={"line_count": 5},
            occurred_at=self.line.issue.issued_at - timedelta(microseconds=1))
        with self.assertRaisesMessage(ValidationError, "不能唯一证明原实物身份"):
            preview_legacy_public_transition(self.manifest)

    def test_current_physical_confirmation_covers_gap_without_changing_history_or_stock(self):
        gap = self.add_summary_gap()
        manifest = self.with_confirmation()
        before_ledgers = self.unchanged_ledgers()
        old_source = copy.deepcopy(self.handoff.source.source_snapshot)
        old_handoff = copy.deepcopy(self.handoff.snapshot)
        old_version = self.handoff.original_order.version
        request_id = uuid.uuid4()
        preview = preview_legacy_public_transition(manifest)
        applied = self.adopt(manifest=manifest, request_id=request_id, expected=preview["manifest_hash"])
        replay = self.adopt(manifest=manifest, request_id=request_id, expected=preview["manifest_hash"])
        self.assertFalse(applied["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(before_ledgers, self.unchanged_ledgers())
        self.assertFalse(PublicStockMovement.objects.exists())
        record = OriginalHandoffPublicTransition.objects.get()
        binding = record.evidence["historical_identity_binding"]
        self.assertFalse(binding["historical_continuity_proven"])
        self.assertEqual(binding["method"], "CURRENT_PHYSICAL_CONFIRMATION_AND_ISSUED_BATCHES")
        self.assertEqual(binding["supplemental_confirmation"], manifest["supplemental_confirmation"])
        self.assertEqual(binding["supplemental_confirmation_sha256"], manifest["supplemental_confirmation_sha256"])
        self.assertEqual(binding["unresolved_historical_gaps"][0]["id"], str(gap.pk))
        self.assertEqual(binding["unresolved_historical_gaps"][0]["after_data"], {"line_count": 5})
        gap.refresh_from_db()
        self.handoff.refresh_from_db()
        self.handoff.source.refresh_from_db()
        self.handoff.original_order.refresh_from_db()
        self.assertEqual(gap.after_data, {"line_count": 5})
        self.assertEqual(self.handoff.source.source_snapshot, old_source)
        self.assertEqual(self.handoff.snapshot, old_handoff)
        self.assertEqual(self.handoff.original_order.version, old_version)
        self.assertEqual(self.handoff.original_order.stock_mode, "LEGACY")
        with self.assertRaises(DatabaseError), transaction.atomic():
            OriginalHandoffPublicTransition.objects.filter(pk=record.pk).update(evidence={})
        altered = copy.deepcopy(manifest)
        altered["supplemental_confirmation"]["question"] += "修改问题"
        altered["supplemental_confirmation_sha256"] = evidence_digest(altered["supplemental_confirmation"])
        with self.assertRaises(Conflict):
            self.adopt(manifest=altered, request_id=request_id, expected=preview["manifest_hash"])
        record.refresh_from_db()
        self.assertEqual(record.evidence["historical_identity_binding"], binding)

    def test_supplemental_confirmation_requires_exact_scope_and_digest(self):
        self.add_summary_gap()
        for key in ("issue_id", "order_id", "candidate_manifest_sha256"):
            with self.subTest(scope_field=key):
                manifest = self.with_confirmation()
                manifest["supplemental_confirmation"]["scope"][key] = str(uuid.uuid4())
                manifest["supplemental_confirmation_sha256"] = evidence_digest(manifest["supplemental_confirmation"])
                with self.assertRaisesMessage(ValidationError, "绑定的领料单"):
                    preview_legacy_public_transition(manifest)
        manifest = self.with_confirmation()
        manifest["supplemental_confirmation_sha256"] = "0" * 64
        with self.assertRaisesMessage(ValidationError, "凭证摘要不符"):
            preview_legacy_public_transition(manifest)
        self.assertFalse(OriginalHandoffPublicTransition.objects.exists())

    def test_supplemental_confirmation_rejects_missing_extra_duplicate_or_mismatched_items(self):
        self.add_summary_gap()
        for kind in ("missing", "extra", "duplicate", "source", "handoff", "bom_line", "material", "shape", "diameter", "thickness", "length"):
            with self.subTest(kind=kind):
                manifest = self.with_confirmation()
                items = manifest["supplemental_confirmation"]["items"]
                if kind == "missing":
                    items.clear()
                elif kind in {"extra", "duplicate"}:
                    items.append(copy.deepcopy(items[0]))
                    if kind == "extra":
                        items[-1]["original_handoff_id"] = str(uuid.uuid4())
                else:
                    field = {"source": "source_id", "handoff": "original_handoff_id", "bom_line": "issued_bom_line_id",
                        "material": "material", "shape": "tube_shape", "diameter": "tube_diameter", "thickness": "tube_thickness",
                        "length": "cutting_length_mm"}[kind]
                    items[0][field] = "不匹配"
                manifest["supplemental_confirmation_sha256"] = evidence_digest(manifest["supplemental_confirmation"])
                with self.assertRaises(ValidationError):
                    preview_legacy_public_transition(manifest)
        self.assertFalse(OriginalHandoffPublicTransition.objects.exists())

    def test_supplemental_confirmation_requires_explicit_confirmation_and_valid_dates(self):
        self.add_summary_gap()
        mutations = {"confirmed": False, "user_answer": "B", "question": "",
            "statement": "历史日志完整", "confirms_current_physical_attributes_not_historical_fact": False,
            "confirmation_id": "不是编号", "recorded_at": (timezone.now() + timedelta(days=1)).isoformat(),
            "confirmed_on": (timezone.localtime(self.line.issue.issued_at).date() - timedelta(days=1)).isoformat()}
        for field, value in mutations.items():
            with self.subTest(field=field):
                manifest = self.with_confirmation()
                manifest["supplemental_confirmation"][field] = value
                manifest["supplemental_confirmation_sha256"] = evidence_digest(manifest["supplemental_confirmation"])
                with self.assertRaises(ValidationError):
                    preview_legacy_public_transition(manifest)
        self.assertFalse(OriginalHandoffPublicTransition.objects.exists())

    def test_supplement_cannot_override_complete_conflicting_physical_evidence(self):
        self.add_summary_gap()
        manifest = self.with_confirmation()
        original = AuditLog.objects.get(pk=manifest["candidates"][0]["historical_audit_id"])
        changed = copy.deepcopy(original.after_data["lines"][0])
        changed["raw_values"]["tube_thickness"] = "1.0"
        AuditLog.objects.create(object_type="BOM", object_id=original.object_id, action="UPDATE",
            before_data=original.after_data, after_data={"lines": [changed]},
            occurred_at=self.line.issue.issued_at - timedelta(microseconds=1))
        with self.assertRaisesMessage(ValidationError, "实物属性已经变化"):
            preview_legacy_public_transition(manifest)

    def test_supplement_cannot_override_actual_batch_or_source_conflict(self):
        self.add_summary_gap()
        manifest = self.with_confirmation()
        inbound = self.line.batch_allocations.get().inbound_line
        inbound.material_snapshot = "铝"
        inbound.save(update_fields=["material_snapshot", "updated_at"])
        with self.assertRaisesMessage(ValidationError, "原入库冻结材质"):
            preview_legacy_public_transition(manifest)
        inbound.material_snapshot = "铁"
        inbound.save(update_fields=["material_snapshot", "updated_at"])
        self.handoff.source.source_hash = "0" * 64
        self.handoff.source.save(update_fields=["source_hash", "updated_at"])
        with self.assertRaises(ValidationError):
            preview_legacy_public_transition(manifest)

    def test_supplement_keeps_unknown_or_incomplete_line_audits_blocked(self):
        self.add_summary_gap()
        manifest = self.with_confirmation()
        AuditLog.objects.create(object_type="BOM", object_id=self.line.conversion_snapshot["bom_id"], action="UPDATE",
            before_data={"line_count": 5},
            after_data={"lines": [{"id": self.manifest["candidates"][0]["bom_line_id"], "material": "铁"}]},
            occurred_at=self.line.issue.issued_at - timedelta(microseconds=1))
        with self.assertRaisesMessage(ValidationError, "完整管材结构属性"):
            preview_legacy_public_transition(manifest)

    def test_supplement_keeps_unknown_audit_changes_blocked(self):
        manifest = self.with_confirmation()
        AuditLog.objects.create(object_type="BOM", object_id=self.line.conversion_snapshot["bom_id"], action="UPDATE",
            before_data={"line_count": 5}, after_data={"line_count": 5, "unrecognized_change": "unknown"},
            occurred_at=self.line.issue.issued_at - timedelta(microseconds=1))
        with self.assertRaisesMessage(ValidationError, "不能唯一证明原实物身份"):
            preview_legacy_public_transition(manifest)

    def test_supplemented_preview_digest_binds_complete_gap_evidence(self):
        self.add_summary_gap()
        manifest = self.with_confirmation()
        receipt = preview_legacy_public_transition(manifest)
        AuditLog.objects.create(object_type="BOM", object_id=self.line.conversion_snapshot["bom_id"], action="UPDATE",
            before_data={"line_count": 5}, after_data={"line_count": 6},
            occurred_at=self.line.issue.issued_at - timedelta(microseconds=1))
        with self.assertRaises(Conflict):
            self.adopt(manifest=manifest, expected=receipt["manifest_hash"])
        self.assertFalse(OriginalHandoffPublicTransition.objects.exists())

    def test_actual_issued_batch_material_must_agree_with_historical_identity(self):
        inbound = self.line.batch_allocations.get().inbound_line
        inbound.material_snapshot = "铝"
        inbound.save(update_fields=["material_snapshot", "updated_at"])
        with self.assertRaisesMessage(ValidationError, "原入库冻结材质"):
            preview_legacy_public_transition(self.manifest)

    def test_split_handoffs_count_original_roots_and_meters_once(self):
        response = self.post(f"/api/v1/metal-processing-sources/{self.line.pk}/handoffs/",
            {"request_id": str(uuid.uuid4()), "original_order_id": self.original_order,
             "factory_id": str(self.f.factory.pk), "handoff_pieces": 4,
             "handoff_date": str(timezone.localdate())}, etag=self.source_etag())
        second = MetalProcessingOriginalHandoff.objects.get(pk=response.data["data"]["operation_id"])
        candidate = copy.deepcopy(self.manifest["candidates"][0])
        candidate.update(original_handoff_id=str(second.pk), handoff_pieces=4,
                         original_handoff_snapshot_hash=evidence_digest(second.snapshot))
        self.manifest["candidates"].append(candidate)
        self.manifest.update(candidate_count=2, handoff_total_pieces=12,
            candidate_manifest_sha256=evidence_digest(self.manifest["candidates"]))
        receipt = preview_legacy_public_transition(self.manifest)
        self.assertEqual(len(receipt["records"]), 2)
        self.adopt(expected=receipt["manifest_hash"])
        self.assertEqual(OriginalHandoffPublicTransition.objects.count(), 2)
        self.assertFalse(PublicStockMovement.objects.exists())
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=True):
            self.good_return(self.good_payload(12))
        self.assertEqual(PublicStockMovement.objects.get().quantity, 12)

    def test_public_mode_rejects_unadopted_then_returns_once_with_original_api(self):
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=True):
            self.good_return(self.good_payload(), expected=400)
        old_mode = self.line.issue.stock_mode
        self.adopt()
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=True):
            context = self.context()
            self.assertTrue(context["transitioned"])
            self.assertEqual(context["stock_mode"], "PUBLIC_V2")
            self.good_return(self.good_payload(9), expected=409)
            self.good_return(self.good_payload(), expected=412, etag='"stale"')
            payload = self.good_payload()
            self.good_return(payload, etag=context["etag"])
            self.good_return(payload, etag=context["etag"])
            self.assertEqual(PublicStockMovement.objects.count(), 1)
            movement = PublicStockMovement.objects.get()
            self.assertEqual((movement.direction, movement.quantity), ("IN", 3))
            self.assertEqual(movement.snapshot["public_transition_id"], str(OriginalHandoffPublicTransition.objects.get().pk))
            self.assertFalse(SemiFinishedStockMovement.objects.exists())
            self.assertEqual(self.context()["remaining_return_pieces"], 5)
        self.line.issue.refresh_from_db()
        self.assertEqual(self.line.issue.stock_mode, old_mode)
        self.assertEqual(OutsourcingOrder.objects.get(pk=self.original_order).stock_mode, "LEGACY")
        # 已接续不能因配置关闭偷偷回到旧半成品账。
        self.good_return(self.good_payload(), expected=400)

    def test_remaining_quantity_change_invalidates_preview_and_legacy_return_is_counted(self):
        old = preview_legacy_public_transition(self.manifest)
        self.good_return(self.good_payload(2))
        with self.assertRaises(Conflict):
            self.adopt(expected=old["manifest_hash"])
        self.adopt()
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=True):
            self.assertEqual(self.context()["remaining_return_pieces"], 6)
            self.good_return(self.good_payload(7), expected=409)
            self.good_return(self.good_payload(6))
        self.assertEqual(PublicStockMovement.objects.get().quantity, 6)
        self.assertEqual(SemiFinishedStockMovement.objects.get().quantity, 2)

    def test_unsprayed_rework_creates_public_descendant_and_never_legacy_stock(self):
        self.adopt()
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=True):
            returned = self.post(f"/api/v1/metal-processing-handoffs/{self.handoff.pk}/returns/",
                {"request_id": str(uuid.uuid4()), "returned_pieces": 3,
                 "received_by_employee_id": str(self.f.employee.pk), "storage_location": "接续暂存",
                 "return_date": str(timezone.localdate()), "remark": "未喷塑退回"}, etag=self.source_etag()).data["data"]
            rework = self.post(f"/api/v1/metal-processing-unsprayed-returns/{returned['id']}/rework/",
                {"request_id": str(uuid.uuid4()), "completed_pieces": 3, "completion_date": str(timezone.localdate())}).data["data"]
            response = self.post(f"/api/v1/metal-processing-reworks/{rework['id']}/orders/",
                {"request_id": str(uuid.uuid4()), "factory_id": str(self.f.factory.pk),
                 "craft_id": str(self.f.spray.pk), "allocated_pieces": 3}, expected=201)
            order = MetalProcessingExternalOrder.objects.get(pk=response.data["data"]["id"])
            self.assertEqual(order.stock_mode, "PUBLIC_V2")
            self.assertEqual(order.output_identity_snapshot, OriginalHandoffPublicTransition.objects.get().public_identity)
            self.assertEqual(self.context()["remaining_return_pieces"], 5)
            self.assertFalse(PublicStockMovement.objects.exists())
            self.assertFalse(SemiFinishedStockMovement.objects.exists())
            base = f"/api/v1/metal-processing-external-orders/{order.pk}/"
            detail = self.client.get(base).data["data"]
            self.post(base + "handoff/", {"request_id": str(uuid.uuid4()), "handoff_pieces": 3,
                "handoff_date": str(timezone.localdate())}, etag=detail["etag"])
            detail = self.client.get(base).data["data"]
            self.post(base + "close/", {"request_id": str(uuid.uuid4()), "remark": "差额结清，允许后续补回"}, etag=detail["etag"])
            detail = self.client.get(base).data["data"]
            self.post(base + "returns/", self.good_payload(3), etag=detail["etag"])
            self.assertEqual(PublicStockMovement.objects.get().quantity, 3)
            self.assertFalse(SemiFinishedStockMovement.objects.exists())
            order.refresh_from_db()
            self.assertEqual(order.status, "COMPLETED")

    def test_closed_original_late_return_keeps_closure_and_uses_public_stock(self):
        self.adopt()
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=True):
            base = f"/api/v1/metal-processing-original-orders/{self.original_order}/"
            detail = self.client.get(base).data["data"]
            self.post(base + "cancel-pending/", {"request_id": str(uuid.uuid4()),
                "allocation_id": detail["parts"][0]["allocation_id"], "remark": "取消未交计划，保留原实交"}, etag=detail["etag"])
            detail = self.client.get(base).data["data"]
            closed = self.post(base + "close/", {"request_id": str(uuid.uuid4()), "remark": "差额8支核对后结清"}, etag=detail["etag"]).data["data"]
            self.good_return(self.good_payload(2, remark=""), expected=400)
            self.good_return(self.good_payload(2, remark="加工厂补回2支"))
            current = self.client.get(base).data["data"]
            self.assertEqual(current["closure"], closed["closure"])
            self.assertEqual(current["original_order_status"], "CLOSED")
            self.assertEqual(PublicStockMovement.objects.get().quantity, 2)
            self.assertFalse(SemiFinishedStockMovement.objects.exists())
