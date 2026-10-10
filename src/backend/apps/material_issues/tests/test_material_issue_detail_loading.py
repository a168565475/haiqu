import copy
import uuid
from decimal import Decimal
from unittest.mock import PropertyMock, patch

from rest_framework.test import APITestCase

from ..api.serializers import MaterialIssueReadSerializer
from ..models import MaterialIssue, MaterialIssueAction, MaterialIssueLine, MaterialIssueStatus
from ..selectors import material_issues_with_context
from . import test_material_flow as flow_fixtures


QUANTITY_FIELDS = (
    "required_quantity",
    "internal_issued_quantity",
    "outsourcing_issued_quantity",
    "order_remaining",
    "available_stock",
    "max_issue_quantity",
)


class MaterialIssueDetailLoadingTests(APITestCase):
    """历史出库详情复用快照和预加载，旧记录仍保留原有回退口径。"""

    def setUp(self):
        super().setUp()
        # 组合复用真实 BOM、采购入库和领料 API fixture，避免继承并重复运行其测试。
        self.flow = flow_fixtures.MaterialIssueFlowTests(
            methodName="test_pipe_actual_three_quantities_and_idempotent_confirmation"
        )
        self.flow.setUp()
        self.client = self.flow.client

    def issue_pipe(self, payload=None):
        issue_id = self.flow.pending(payload)
        response = self.flow.action(issue_id, "confirm-issue", {"request_id": str(uuid.uuid4())})
        return MaterialIssue.objects.get(pk=issue_id), copy.deepcopy(response.data["data"])

    def detail(self, issue):
        response = self.client.get(f"/api/v1/material-issues/{issue.pk}/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]

    def issued_event(self, issue):
        return issue.audit_events.get(action=MaterialIssueAction.ISSUED)

    def set_live_requirement(self, issue):
        requirement = issue.lines.get().requirement
        requirement.required_quantity = Decimal("60")
        requirement.internal_issued_quantity = Decimal("18")
        requirement.outsourcing_issued_quantity = Decimal("6")
        requirement.save(update_fields=[
            "required_quantity", "internal_issued_quantity", "outsourcing_issued_quantity", "updated_at"
        ])
        return {
            "required_quantity": "60.0000",
            "internal_issued_quantity": "18.0000",
            "outsourcing_issued_quantity": "6.0000",
            "order_remaining": "36.0000",
            "available_stock": "24",
            "max_issue_quantity": "24",
        }

    def assert_quantities(self, row, expected):
        self.assertEqual({field: row[field] for field in QUANTITY_FIELDS}, expected)

    def test_complete_pipe_snapshot_skips_live_stock_and_keeps_entire_detail(self):
        issue, expected = self.issue_pipe()
        self.set_live_requirement(issue)
        self.flow.pipe_balance.quantity = Decimal("90")
        self.flow.pipe_balance.meter_quantity = Decimal("274.50")
        self.flow.pipe_balance.save(update_fields=["quantity", "meter_quantity"])

        with (
            patch("apps.material_issues.api.serializers.line_stock", side_effect=AssertionError("不应读取实时库存")),
            patch("apps.material_issues.material_flow.batch_candidates", side_effect=AssertionError("不应扫描入库批次")),
        ):
            actual = self.detail(issue)

        self.assertEqual(actual, expected)
        self.assertEqual(actual["lines"][0]["bar_count"], "2")
        self.assertEqual(actual["lines"][0]["meters"], "6.10")
        self.assertEqual(len(actual["lines"][0]["batch_allocations"]), 1)

    def test_complete_snapshot_does_not_access_live_requirement(self):
        issue, expected = self.issue_pipe()
        loaded = material_issues_with_context().get(pk=issue.pk)
        with (
            patch.object(MaterialIssueLine, "requirement", new_callable=PropertyMock,
                         side_effect=AssertionError("完整历史快照不应读取实时订单额度")),
            patch("apps.material_issues.api.serializers.line_stock", side_effect=AssertionError("不应读取实时库存")),
        ):
            actual = MaterialIssueReadSerializer(loaded).data
        self.assertEqual(actual, expected)

    def test_zero_snapshot_values_are_preserved_without_fallback(self):
        issue, _ = self.issue_pipe()
        event = self.issued_event(issue)
        for zero in ("0", 0):
            with self.subTest(zero=zero):
                snapshot = event.snapshot["issued_line_snapshots"][0]
                snapshot.update({field: zero for field in QUANTITY_FIELDS})
                event.save(update_fields=["snapshot"])
                with patch("apps.material_issues.api.serializers.line_stock",
                           side_effect=AssertionError("零值也是有效历史快照")):
                    row = self.detail(issue)["lines"][0]
                self.assert_quantities(row, {field: zero for field in QUANTITY_FIELDS})

    def test_legacy_issued_without_event_uses_live_fallback(self):
        issue, _ = self.issue_pipe()
        expected = self.set_live_requirement(issue)
        self.issued_event(issue).delete()
        with patch("apps.material_issues.api.serializers.line_stock", return_value=Decimal("24")) as stock:
            row = self.detail(issue)["lines"][0]
        stock.assert_called_once()
        self.assert_quantities(row, expected)

    def test_legacy_issued_without_matching_line_snapshot_uses_live_fallback(self):
        issue, _ = self.issue_pipe()
        expected = self.set_live_requirement(issue)
        event = self.issued_event(issue)
        original = copy.deepcopy(event.snapshot)
        unrelated = copy.deepcopy(original["issued_line_snapshots"][0])
        unrelated["line_id"] = str(uuid.uuid4())
        for snapshots in (None, [], [unrelated]):
            with self.subTest(snapshots=snapshots):
                event.snapshot = copy.deepcopy(original)
                if snapshots is None:
                    event.snapshot.pop("issued_line_snapshots")
                else:
                    event.snapshot["issued_line_snapshots"] = snapshots
                event.save(update_fields=["snapshot"])
                with patch("apps.material_issues.api.serializers.line_stock", return_value=Decimal("24")) as stock:
                    row = self.detail(issue)["lines"][0]
                stock.assert_called_once()
                self.assert_quantities(row, expected)

    def test_partial_issued_snapshot_keeps_saved_values_and_falls_back_for_missing_field(self):
        issue, _ = self.issue_pipe()
        live_values = self.set_live_requirement(issue)
        event = self.issued_event(issue)
        original = copy.deepcopy(event.snapshot)
        saved = original["issued_line_snapshots"][0]
        for missing in QUANTITY_FIELDS:
            with self.subTest(missing=missing):
                event.snapshot = copy.deepcopy(original)
                event.snapshot["issued_line_snapshots"][0].pop(missing)
                event.save(update_fields=["snapshot"])
                with patch("apps.material_issues.api.serializers.line_stock", return_value=Decimal("24")):
                    row = self.detail(issue)["lines"][0]
                expected = {field: saved[field] for field in QUANTITY_FIELDS}
                expected[missing] = live_values[missing]
                self.assert_quantities(row, expected)

    def test_unissued_statuses_continue_to_query_live_stock(self):
        issue_id = self.flow.create_issue().data["data"]["id"]
        issue = MaterialIssue.objects.get(pk=issue_id)
        for status in (MaterialIssueStatus.DRAFT, MaterialIssueStatus.PENDING_REVIEW, MaterialIssueStatus.RETURNED):
            with self.subTest(status=status):
                if status == MaterialIssueStatus.PENDING_REVIEW:
                    self.flow.action(issue_id, "submit")
                elif status == MaterialIssueStatus.RETURNED:
                    self.flow.action(issue_id, "return", {"reason": "核对领料数量"})
                with patch("apps.material_issues.api.serializers.line_stock", return_value=Decimal("24")) as stock:
                    data = self.detail(issue)
                stock.assert_called_once()
                self.assertEqual(data["status"], status)
                self.assertEqual(data["lines"][0]["available_stock"], "24")
                self.assertEqual(data["lines"][0]["max_issue_quantity"], "24")

    def test_prefetched_multiple_pipe_lines_and_audit_events_need_no_extra_queries(self):
        other_part = copy.copy(self.flow.f.profile)
        other_part.pk = None
        other_part.component_identity = uuid.uuid4()
        other_part.line_number += 1
        other_part.part_name = "详情性能测试后脚管"
        other_part.save()
        payload = self.flow.issue_payload()
        requirements = [
            row for row in self.flow.requirements()
            if row.get("conversion_snapshot", {}).get("kind") == "PIPE"
        ]
        self.assertEqual(len(requirements), 2)
        payload["lines"] = [
            {"requirement_id": row["requirement_id"], "requested_quantity": "12"}
            for row in reversed(requirements)
        ]
        issue, expected = self.issue_pipe(payload)
        loaded = material_issues_with_context().get(pk=issue.pk)
        # 模拟上游预加载顺序不同，输出仍须按明细行号、审计时间稳定排序。
        loaded._prefetched_objects_cache["lines"]._result_cache.reverse()
        loaded._prefetched_objects_cache["audit_events"]._result_cache.reverse()
        with (
            patch("apps.material_issues.api.serializers.line_stock", side_effect=AssertionError("不应读取实时库存")),
            self.assertNumQueries(0),
        ):
            actual = MaterialIssueReadSerializer(loaded).data
        self.assertEqual(actual, expected)
        self.assertEqual([line["line_number"] for line in actual["lines"]], [1, 2])
        self.assertEqual([event["action"] for event in actual["audit_events"]], [
            MaterialIssueAction.CREATED, MaterialIssueAction.SUBMITTED, MaterialIssueAction.ISSUED,
        ])

    def test_issued_semi_finished_snapshot_stays_fixed_after_stock_changes(self):
        payload, balance = self.flow.semi_payload(quantity="5", returned_quantity=12)
        issue, expected = self.issue_pipe(payload)
        balance.quantity = Decimal("3")
        balance.save(update_fields=["quantity"])
        loaded = material_issues_with_context().get(pk=issue.pk)
        with self.assertNumQueries(0):
            actual = MaterialIssueReadSerializer(loaded).data
        self.assertEqual(actual, expected)
        self.assertEqual(actual["lines"][0]["line_type"], "SEMI")
        self.assertEqual(actual["lines"][0]["conversion_snapshot"]["raw_deducted_bar_count"], "0")
