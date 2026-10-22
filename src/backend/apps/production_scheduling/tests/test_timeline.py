from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from apps.production_scheduling.timeline import TimelineQuerySerializer, event_row, timeline_page, production_timeline
from .test_detail_reporting import DetailReportingTests


class TimelineFormattingTests(SimpleTestCase):
    def test_event_details_whitelist_excludes_prices_and_request_metadata(self):
        row = event_row(identity="audit:1", kind="BOM", label="BOM", action="UPDATE", actor="张三",
            at=datetime(2026, 10, 22, tzinfo=timezone.utc), before={"status": "DRAFT", "secret": "x"},
            after={"status": "CONFIRMED", "total_amount": "1000", "ip_address": "127.0.0.1"})
        self.assertEqual(row["title"], "修改 · BOM")
        self.assertEqual(row["changes"], [{"label": "状态", "before": "DRAFT", "after": "CONFIRMED"}])

    def test_query_limits_and_search_pagination(self):
        self.assertFalse(TimelineQuerySerializer(data={"page": 0, "page_size": 101}).is_valid())
        rows = [{"title": "创建采购单", "actor_name": "张三", "document_number": f"CG{i}"} for i in range(3)]
        result = timeline_page(rows, {"search": "张三 CG", "page": 2, "page_size": 2})
        self.assertEqual(result["meta"]["total"], 3)
        self.assertEqual(result["data"], [rows[2]])


class ProductionTimelineTests(DetailReportingTests):
    # 仅以明确的方法标签执行新增用例，不重复运行继承的历史测试。
    def test_timeline_returns_sorted_real_audit_and_search(self):
        from apps.core.audit import write_audit_log
        write_audit_log(object_type="PRODUCTION_SCHEDULE", object_id=self.schedule.pk,
                        action="UPDATED", actor_employee=self.employee, after_data={"reason": "时间轴测试"})
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_authenticate(self.user)
        response = self.client.get(f"/api/v1/production-schedules/{self.schedule.pk}/timeline/")
        self.assertEqual(response.status_code, 200, response.data)
        dates = [row["occurred_at"] for row in response.data["data"]]
        self.assertEqual(dates, sorted(dates))
        self.assertTrue(any(row["title"] == "修改 · 排产单" for row in response.data["data"]))
        missing = self.client.get(f"/api/v1/production-schedules/{self.schedule.pk}/timeline/", {"search": "不存在的事件"})
        self.assertEqual(missing.data["meta"]["total"], 0)
        invalid = self.client.get(f"/api/v1/production-schedules/{self.schedule.pk}/timeline/", {"page_size": 101})
        self.assertEqual(invalid.status_code, 400)

    def test_timeline_does_not_leak_other_modules_without_permission(self):
        from apps.production_scheduling.selectors import schedules_with_context
        schedule = schedules_with_context().get(pk=self.schedule.pk)
        request = SimpleNamespace(user=self.user, employee=self.employee)
        with patch("apps.production_scheduling.timeline.has_permission", return_value=False), \
             patch("apps.production_scheduling.timeline._sources_for_tasks") as external, \
             patch("apps.production_scheduling.timeline_metal.has_permission", return_value=False):
            from apps.outsourcing.models import OutsourcingOrder, TubeOutsourcingOrder
            from apps.material_issues.models import MetalProcessingExternalOrder
            external.return_value = (OutsourcingOrder.objects.none(), MetalProcessingExternalOrder.objects.none(),
                                     TubeOutsourcingOrder.objects.none(), request)
            rows = production_timeline(request, schedule)
        self.assertTrue(all(row["kind"] == "PRODUCTION_SCHEDULE" for row in rows))
