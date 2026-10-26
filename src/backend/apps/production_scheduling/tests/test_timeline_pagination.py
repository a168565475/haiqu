"""时间线分页的隔离数据库回归；夹具不代表真实员工业务验收。"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db.models.query import ModelIterable
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory, APITestCase

from apps.access_control.models import RoleActionGrant, RoleGrantResource
from apps.audit.models import AuditLog
from apps.inventory.internal_receipt_models import InternalSemiFinishedReceipt
from apps.inventory.models import Warehouse, WarehouseZone
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.workshop_config.models import Craft, Workshop
from apps.workshop_reporting.models import WageScheme, WageSchemeEvent, WorkReport
from apps.workshop_reporting.tests import test_workshop_reporting_api as reporting_fixtures

from ..selectors import accessible_production_schedules, schedules_with_context
from ..timeline import production_timeline, timeline_page


@override_settings(
    ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True,
    SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True,
    DEV_AUTO_LOGIN_ENABLED=False,
)
class TimelinePaginationTests(APITestCase):
    def setUp(self):
        # 只复用模型准备方法，不继承旧测试及其关闭权限的设置。
        reporting_fixtures.WorkshopReportingApiTests.setUp(self)
        self.url = f"/api/v1/production-schedules/{self.schedule.pk}/timeline/"
        self.at = timezone.now() - timedelta(days=10)

    def audit(self, *, kind="PRODUCTION_SCHEDULE", object_id=None, action="UPDATED",
              actor="分页测试员", at=None, before=None, after=None):
        return AuditLog.objects.create(
            object_type=kind, object_id=object_id or self.schedule.pk, action=action,
            actor_employee=self.employee, actor_name_snapshot=actor,
            occurred_at=at or self.at, before_data=before or {}, after_data=after or {},
        )

    def complete_page(self, params, *, user=None, employee=None):
        request = APIRequestFactory().get(self.url, params)
        request.user = get_user_model().objects.get(pk=(user or self.user).pk)
        request.employee = employee or self.employee
        request.parser_context = {"view": SimpleNamespace(
            action="timeline", action_permission_map={
                "timeline": "production_scheduling.view_productionschedule",
            },
        )}
        schedule = schedules_with_context(
            accessible_production_schedules(request), request=request,
        ).get(pk=self.schedule.pk)
        return timeline_page(production_timeline(request, schedule), {
            "search": "", "page": 1, "page_size": 20, **params,
        })

    def large_audits(self):
        return [self.audit(
            at=self.at + timedelta(seconds=index),
            before={"status": "ACTIVE", "private_snapshot": "前" * 8192},
            after={"status": "VOID", "reason": f"第{index}次修改", "private_snapshot": "后" * 8192},
        ) for index in range(40)]

    def assert_page_json_loads(self, params, audits, expected_loads):
        expected = self.complete_page(params)
        tracked_ids = {event.pk for event in audits}
        json_loads = []
        original_iter = ModelIterable.__iter__

        def observe_real_instances(iterable):
            for instance in original_iter(iterable):
                if isinstance(instance, AuditLog) and instance.pk in tracked_ids:
                    # 只看已载入字段；不访问 deferred 属性，不替换真实查询或结果。
                    if {"before_data", "after_data"} & instance.__dict__.keys():
                        json_loads.append(instance.pk)
                yield instance

        with patch.object(ModelIterable, "__iter__", observe_real_instances):
            response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, expected)
        self.assertEqual(len(json_loads), expected_loads)
        self.assertEqual({f"audit:{pk}" for pk in json_loads}, {
            row["id"] for row in response.data["data"] if row["id"].startswith("audit:")
        })
        return response

    def scheme(self, *, number="GJ-TIMELINE-001", workshop=None, craft=None):
        return WageScheme.objects.create(
            scheme_number=number, product_line=self.product_line,
            workshop=workshop or self.workshop, scope_craft=craft or self.craft,
            schedule_product=self.schedule_product, product_name_snapshot="时间线产品",
            product_number_snapshot="TIMELINE-PRODUCT", operation_product_name_snapshot="时间线工序",
            created_by_employee=self.employee, updated_by_employee=self.employee,
        )

    def wage_event(self, scheme):
        event = WageSchemeEvent.objects.create(
            scheme=scheme, action="CREATED", scheme_revision=1,
            actor_employee=self.employee, comment="真实工价事件",
        )
        WageSchemeEvent.objects.filter(pk=event.pk).update(created_at=self.at)
        return event

    def deleted_event(self, kind, *, has_creation=False, workshop=None):
        object_id = uuid4()
        original_at = self.at - timedelta(days=1)
        snapshot = {
            "product_line_id": str(self.product_line.pk),
            "workshop_id": str((workshop or self.workshop).pk),
            "recorder_name_snapshot": "删除前记录员", "submitted_by_name": "删除前提交员",
            "created_at": original_at.isoformat(), "submitted_at": original_at.isoformat(),
            "report_number" if kind == "WORK_REPORT" else "receipt_number": f"REMOVED-{object_id.hex[:8]}",
            "reason": "保留删除归属", "private_snapshot": {"secret": "不能展示"},
        }
        deletion = self.audit(kind=kind, object_id=object_id, action="DELETE", before=snapshot)
        creation = self.audit(kind=kind, object_id=object_id, action="CREATED", at=original_at) if has_creation else None
        return deletion, creation, original_at

    def test_first_page_loads_only_two_of_forty_audit_json_snapshots(self):
        response = self.assert_page_json_loads({"page_size": 2}, self.large_audits(), 2)
        self.assertEqual(response.data["meta"]["total"], 40)
        self.assertEqual(response.data["data"][0]["changes"], [
            {"label": "状态", "before": "有效", "after": "已作废"},
            {"label": "原因", "before": "", "after": "第0次修改"},
        ])

    def test_later_empty_and_whitespace_pages_equal_complete_output(self):
        audits = self.large_audits()
        for params, loads in [
            ({"page": 20, "page_size": 2, "search": ""}, 2),
            ({"page": 21, "page_size": 2, "search": ""}, 0),
            ({"page": 1, "page_size": 2, "search": "  \t "}, 2),
            ({"page": 1, "page_size": 2, "search": "没有匹配事件"}, 0),
        ]:
            with self.subTest(params=params):
                self.assert_page_json_loads(params, audits, loads)

    def test_unicode_chinese_multiword_search_does_not_match_changes(self):
        first = self.audit(actor="Straße 张三", after={"reason": "备注专用关键词"})
        second = self.audit(actor="张三", at=self.at + timedelta(seconds=1))
        self.audit(actor="Straße 李四", at=self.at + timedelta(seconds=2))
        for search, ids in [
            ("  STRASSE  张三 pc-wg ", [f"audit:{first.pk}"]),
            ("修改 张三", [f"audit:{first.pk}", f"audit:{second.pk}"]),
            ("备注专用关键词", []),
            ("STRASSE 不存在的人", []),
        ]:
            with self.subTest(search=search):
                params = {"search": search, "page_size": 2}
                response = self.client.get(self.url, params)
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data, self.complete_page(params))
                self.assertEqual([row["id"] for row in response.data["data"]], ids)
                self.assertEqual(response.data["meta"]["total"], len(ids))

    def test_deleted_origins_keep_time_and_deduplicate_formal_creations(self):
        legacy = [self.deleted_event(kind) for kind in ("WORK_REPORT", "INTERNAL_SEMI_RECEIPT")]
        audited = [self.deleted_event(kind, has_creation=True) for kind in ("WORK_REPORT", "INTERNAL_SEMI_RECEIPT")]
        finished, _, _ = self.deleted_event("FINISHED_GOODS_RECEIPT")
        params = {"page_size": 100}
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, self.complete_page(params))
        rows = {row["id"]: row for row in response.data["data"]}
        self.assertEqual(response.data["meta"]["total"], 9)
        for deletion, _, original_at in legacy:
            origin = rows[f"deleted-origin:{deletion.pk}"]
            self.assertEqual(origin["occurred_at"], original_at)
            self.assertIsNone(origin["detail_path"])
            self.assertIn(f"audit:{deletion.pk}", rows)
        for deletion, creation, original_at in audited:
            self.assertNotIn(f"deleted-origin:{deletion.pk}", rows)
            self.assertEqual(rows[f"audit:{creation.pk}"]["occurred_at"], original_at)
            self.assertIn(f"audit:{deletion.pk}", rows)
        self.assertNotIn(f"deleted-origin:{finished.pk}", rows)

    def test_same_time_mixed_sources_paginate_by_complete_identity(self):
        scheme = self.scheme()
        wage_events = [self.wage_event(scheme), self.wage_event(scheme)]
        audits = [self.audit(), self.audit()]
        warehouse = Warehouse.objects.create(
            warehouse_number="TIMELINE-SEMI", warehouse_name="时间线半成品仓", warehouse_type="SEMI_FINISHED",
        )
        zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name="时间线库区")
        receipt = InternalSemiFinishedReceipt.objects.create(
            receipt_number="RK-TIMELINE-001", request_id=uuid4(), request_payload_hash="d" * 64,
            schedule_product=self.schedule_product, completed_craft=self.craft, plan_category="METAL",
            receipt_date=timezone.localdate(), zone=zone, actor_employee=self.employee,
            submitted_by_employee=self.employee, submitted_at=self.at,
            confirmed_by_employee=self.employee, confirmed_at=self.at,
            source_revision_hash="e" * 64, source_snapshot={},
        )
        report = WorkReport.objects.create(
            report_number="BG-TIMELINE-001", production_date=timezone.localdate(),
            task_number_snapshot=self.task.task_number, order_number_snapshot=self.task.order_number,
            product_name_snapshot="时间线产品", product_number_snapshot="TIMELINE-PRODUCT",
            recorder_name_snapshot=self.employee.display_name, product_line=self.product_line,
            schedule_product=self.schedule_product, workshop=self.workshop, scheme=scheme,
            scheme_version_snapshot=1, recorder_employee=self.employee, updated_by_employee=self.employee,
            total_amount=Decimal("0"), client_request_id=uuid4(), request_payload_hash="f" * 64,
        )
        WorkReport.objects.filter(pk=report.pk).update(created_at=self.at)
        expected_ids = sorted([
            *[f"audit:{event.pk}" for event in audits], *[f"wage:{event.pk}" for event in wage_events],
            f"internal:{receipt.pk}:created", f"internal:{receipt.pk}:confirmed", f"report:{report.pk}:created",
        ])
        actual_ids = []
        for page in range(1, 5):
            params = {"page": page, "page_size": 2}
            response = self.client.get(self.url, params)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data, self.complete_page(params))
            self.assertEqual(response.data["meta"]["total"], len(expected_ids))
            self.assertTrue(all(row["occurred_at"] == self.at for row in response.data["data"]))
            actual_ids.extend(row["id"] for row in response.data["data"])
        self.assertEqual(actual_ids, expected_ids)

    def test_real_workshop_permissions_hide_other_sources_and_deleted_reports(self):
        other_workshop = Workshop.objects.get(name="车缝车间")
        other_craft = Craft.objects.create(
            craft_type="INTERNAL", workshop=other_workshop, name="时间线另一个工艺", plan_category="SEWING",
        )
        visible_wage = self.wage_event(self.scheme())
        hidden_wage = self.wage_event(self.scheme(number="GJ-TIMELINE-HIDDEN", workshop=other_workshop, craft=other_craft))
        visible_deleted, _, _ = self.deleted_event("WORK_REPORT")
        hidden_deleted, _, _ = self.deleted_event("WORK_REPORT", workshop=other_workshop)
        schedule_audit = self.audit()
        hidden_bom = self.audit(kind="BOM", object_id=self.bom.pk, actor="不可见模块操作人")

        user = get_user_model().objects.create_user(username="timeline-workshop-reader")
        employee = Employee.objects.create(user=user, employee_code="TIMELINE-READER", display_name="时间线车间查看员")
        group = Group.objects.create(name="TIMELINE-WORKSHOP-READER")
        role = RoleProfile.objects.create(role_code="TIMELINE_WORKSHOP_READER", display_name="时间线查看员", auth_group=group)
        EmployeeRoleAssignment.objects.create(
            employee=employee, role_profile=role, effective_from=timezone.now() - timedelta(days=1),
        )
        for code in ("production_scheduling.view_productionschedule", "workshop_reporting.view_wagescheme",
                     "workshop_reporting.view_workreport"):
            app, codename = code.split(".")
            permission = Permission.objects.get(content_type__app_label=app, codename=codename)
            group.permissions.add(permission)
            grant = RoleActionGrant.objects.create(role=role, permission=permission, scope="WORKSHOP")
            RoleGrantResource.objects.create(grant=grant, workshop=self.workshop)
        client = APIClient()
        client.force_authenticate(user)
        params = {"page_size": 100}
        response = client.get(self.url, params)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, self.complete_page(params, user=user, employee=employee))
        ids = {row["id"] for row in response.data["data"]}
        self.assertEqual(ids, {
            f"audit:{schedule_audit.pk}", f"wage:{visible_wage.pk}",
            f"audit:{visible_deleted.pk}", f"deleted-origin:{visible_deleted.pk}",
        })
        self.assertEqual(response.data["meta"]["total"], 4)
        self.assertTrue(ids.isdisjoint({
            f"wage:{hidden_wage.pk}", f"audit:{hidden_deleted.pk}",
            f"deleted-origin:{hidden_deleted.pk}", f"audit:{hidden_bom.pk}",
        }))
