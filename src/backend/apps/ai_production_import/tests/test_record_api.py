"""隔离测试库中的记录/API 集成回归；预置识别结果，不调用 AI，不代替业务验收。"""

from copy import deepcopy
from uuid import uuid4

from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.boms.api.serializers import FIXED_BOM_SECTIONS
from apps.boms.models import Bom
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee
from apps.production_tasks.models import ProductionTask, ProductionTaskStatus
from apps.production_tasks.tests import test_production_task_api as fixtures

from ..models import AiImportState, AiProductionImport


ROOT = "/api/v1/ai-production-imports/"


def recognition_result():
    return {
        "task": {"task_number": {"status": "EXTRACTED", "value": "HT26149"}},
        "products": [{"product_key": "product-1"}], "boms": [], "issues": [],
        "additional_tasks": [{
            "task_key": "second", "task": {"task_number": {"status": "EXTRACTED", "value": "HT26150"}},
            "products": [{"product_key": "product-2"}], "boms": [], "issues": [],
        }],
    }


def review_draft(task_key="main"):
    return {"task_key": task_key, "task_payload": {"task_number": f"{task_key}-人工核对"},
            "bom_plans": [{"product_key": f"{task_key}-product", "sections": []}]}


@override_settings(ACCESS_MANAGEMENT_ENABLED=False, MODULE_ACCESS_ENABLED=False, DEV_AUTO_LOGIN_ENABLED=False)
class AiImportRecordApiTests(APITestCase):
    # 只复用资料准备和合法任务请求，不继承原类的全部测试。
    payload = fixtures.ProductionTaskApiTests.payload

    def setUp(self):
        fixtures.ProductionTaskApiTests.setUp(self)
        self.import_permission = Permission.objects.get(
            content_type__app_label="production_task_imports", codename="import_production_task")
        self.user.user_permissions.add(self.import_permission)
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label="boms"))
        self.client.force_authenticate(None)
        self.client.force_login(self.user)
        self.record = self.make_record()

    def make_record(self, **overrides):
        values = {
            "owner": self.employee, "client_request_id": uuid4(), "original_name": "api-fixture.xlsx",
            "sha256": "a" * 64, "size_bytes": 100, "result": recognition_result(),
            "source": {"source_index": {"cell-1": {"kind": "cell", "ref": "A1"}},
                       "sheets": [{"name": "任务单", "cells": [{"source_id": "cell-1", "text": "预置测试文本"}]}]},
        }
        values.update(overrides)
        return AiProductionImport.objects.create(**values)

    def send(self, action="", data=None, *, method="post", record=None, etag=None):
        target = record or self.record
        target.refresh_from_db()
        headers = {"HTTP_IF_MATCH": etag_for_instance(target) if etag is None else etag}
        path = f"{ROOT}{target.pk}/{action + '/' if action else ''}"
        return getattr(self.client, method)(path, {} if data is None else data, format="json", **headers)

    def unknown_payload(self, *, product_key="product-1"):
        payload = self.payload(currency_id=None, includes_tax=None, tax_rate=None,
                               freight_amount=None, other_fee_amount=None)
        payload["products"][0].update(client_key=product_key, currency_id=None, unit_price=None, exchange_rate=None)
        payload["products"][0]["details"][0]["is_selected"] = None
        return payload

    def test_owner_scope_applies_to_list_read_save_switch_restore_delete_and_create(self):
        other = Employee.objects.create(employee_code="AI_IMPORT_OTHER", display_name="其他账号测试员工")
        foreign = self.make_record(owner=other)
        listed = self.client.get(ROOT)
        self.assertEqual(listed.status_code, 200, listed.data)
        self.assertEqual([str(item["id"]) for item in listed.data["results"]], [str(self.record.pk)])
        self.assertEqual(self.client.get(f"{ROOT}{foreign.pk}/").status_code, 404)
        original = deepcopy(foreign.source)
        for method, action, data in [
            ("patch", "", review_draft()), ("delete", "", {}),
            ("post", "select-task", {"task_key": "second"}), ("post", "restore-review", {}),
            ("post", "remap", {}),
            ("post", "create-task", {"task_key": "main", "payload": {"task_number": "blocked"}}),
            ("post", "create-boms", {"task_key": "main", "plans": [{}]}),
        ]:
            with self.subTest(action=action, method=method):
                result = self.send(action, data, method=method, record=foreign)
                self.assertEqual(result.status_code, 404, result.data)
        foreign.refresh_from_db()
        self.assertEqual(foreign.source, original)
        self.assertIsNone(foreign.task_id)
        self.assertEqual(foreign.bom_ids, [])

    def test_import_and_add_task_permissions_are_both_required_for_record_access(self):
        create_permission = Permission.objects.get(content_type__app_label="production_tasks", codename="add_productiontask")
        for permission in (self.import_permission, create_permission):
            with self.subTest(permission=permission.codename):
                self.user.user_permissions.remove(permission)
                self.assertEqual(self.client.get(ROOT).status_code, 403)
                denied = self.send("select-task", {"task_key": "second"})
                self.assertEqual(denied.status_code, 403, denied.data)
                self.user.user_permissions.add(permission)
        self.record.refresh_from_db()
        self.assertNotIn("active_task_key", self.record.source)

    def test_bom_creation_requires_its_own_permission(self):
        permission = Permission.objects.get(content_type__app_label="boms", codename="add_bom")
        self.user.user_permissions.remove(permission)
        result = self.send("create-boms", {"task_key": "main", "plans": [{}]})
        self.assertEqual(result.status_code, 403, result.data)
        self.assertEqual(self.client.get(ROOT).status_code, 200)

    def test_anonymous_archived_employee_and_session_without_csrf_cannot_mutate(self):
        self.assertEqual(APIClient().get(ROOT).status_code, 401)
        self.employee.archived_at = timezone.now()
        self.employee.save(update_fields=["archived_at"])
        self.assertEqual(self.send("select-task", {"task_key": "second"}).status_code, 401)
        self.employee.archived_at = None
        self.employee.save(update_fields=["archived_at"])
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        read = csrf_client.get(f"{ROOT}{self.record.pk}/")
        self.assertEqual(read.status_code, 200, read.data)
        denied = csrf_client.patch(f"{ROOT}{self.record.pk}/", review_draft(), format="json", HTTP_IF_MATCH=read["ETag"])
        self.assertEqual(denied.status_code, 403, denied.data)
        self.record.refresh_from_db()
        self.assertNotIn("review_draft", self.record.source)

    def test_invalid_uuid_record_paths_return_404_before_database_lookup(self):
        for method, action, data in [
            ("get", "", None), ("patch", "", review_draft()), ("delete", "", {}),
            ("post", "select-task", {"task_key": "second"}), ("post", "restore-review", {}),
            ("post", "remap", {}),
            ("post", "create-task", {"task_key": "main", "payload": {"task_number": "blocked"}}),
            ("post", "create-boms", {"task_key": "main", "plans": [{}]}),
        ]:
            with self.subTest(action=action, method=method):
                path = f"{ROOT}invalid-uuid/{action + '/' if action else ''}"
                response = getattr(self.client, method)(path, data, format="json")
                self.assertEqual(response.status_code, 404)

    def test_all_mutations_require_current_etag_before_changing_record(self):
        original = deepcopy(self.record.source)
        for method, action, data in [
            ("patch", "", review_draft()), ("delete", "", {}),
            ("post", "select-task", {"task_key": "second"}), ("post", "restore-review", {}),
            ("post", "remap", {}),
            ("post", "create-task", {"task_key": "main", "payload": {"task_number": "blocked"}}),
            ("post", "create-boms", {"task_key": "main", "plans": [{}]}),
        ]:
            for etag, expected in (("", 428), ('"stale"', 412)):
                with self.subTest(action=action, method=method, etag=etag):
                    result = self.send(action, data, method=method, etag=etag)
                    self.assertEqual(result.status_code, expected, result.data)
        self.record.refresh_from_db()
        self.assertEqual(self.record.source, original)
        saved = self.send(data=review_draft(), method="patch")
        self.assertEqual(saved.status_code, 200, saved.data)
        switched = self.send("select-task", {"task_key": "second"}, etag=saved["ETag"])
        self.assertEqual(switched.status_code, 200, switched.data)
        stale = self.send(data=review_draft(), method="patch", etag=saved["ETag"])
        self.assertEqual(stale.status_code, 412, stale.data)

    def test_task_key_rejects_missing_or_old_task_on_review_and_both_creation_endpoints(self):
        selected = self.send("select-task", {"task_key": "second"})
        self.assertEqual(selected.status_code, 200, selected.data)
        for key in (None, "main"):
            prefix = {} if key is None else {"task_key": key}
            for method, action, data in [
                ("patch", "", {**prefix, "task_payload": {"task_number": "wrong"}, "bom_plans": []}),
                ("post", "create-task", {**prefix, "payload": {"task_number": "wrong"}}),
                ("post", "create-boms", {**prefix, "plans": [{}]}),
            ]:
                with self.subTest(key=key, action=action):
                    result = self.send(action, data, method=method)
                    self.assertEqual(result.status_code, 409, result.data)
        self.record.refresh_from_db()
        self.assertEqual(self.record.source["active_task_key"], "second")
        self.assertIsNone(self.record.source.get("review_draft"))
        self.assertIsNone(self.record.task_id)
        self.assertEqual(self.record.bom_ids, [])

    def test_switch_persists_selected_task_and_separate_review_drafts_after_reopen(self):
        original_source = deepcopy(self.record.source)
        for key in ("main", "second"):
            if key != "main":
                self.assertEqual(self.send("select-task", {"task_key": key}).status_code, 200)
            saved = self.send(data=review_draft(key), method="patch")
            self.assertEqual(saved.status_code, 200, saved.data)
        for key in ("main", "second", "main"):
            result = self.send("select-task", {"task_key": key})
            self.assertEqual(result.status_code, 200, result.data)
            reopened = self.client.get(f"{ROOT}{self.record.pk}/")
            self.assertEqual(reopened.status_code, 200, reopened.data)
            self.assertEqual(reopened.data["data"]["active_task_key"], key)
            self.assertEqual(reopened.data["data"]["review_draft"], review_draft(key))
            self.assertEqual(reopened["ETag"], result["ETag"])
        self.record.refresh_from_db()
        self.assertEqual(self.record.source["source_index"], original_source["source_index"])
        self.assertEqual(self.record.source["sheets"], original_source["sheets"])
        self.assertEqual(self.record.result, recognition_result())
        invalid = self.send("select-task", {"task_key": "other-record-task"})
        self.assertEqual(invalid.status_code, 400, invalid.data)
        self.record.refresh_from_db()
        self.assertEqual(self.record.source["active_task_key"], "main")

    def test_old_single_task_record_can_save_without_task_key(self):
        result = recognition_result()
        result.pop("additional_tasks")
        legacy = self.make_record(result=result)
        draft = review_draft()
        draft.pop("task_key")
        saved = self.send(data=draft, method="patch", record=legacy)
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(saved.data["data"]["review_draft"], draft)
        self.assertEqual(saved.data["data"]["active_task_key"], "main")

    def test_restore_preserves_both_versions_and_task_specific_drafts(self):
        old_result = recognition_result()
        old_result["task"]["task_number"]["value"] = "HT-old"
        previous = {"result": old_result, "review_draft": review_draft("second"), "active_task_key": "second",
                    "task_states": {"main": {"state": "REVIEW", "review_draft": review_draft("main")}}, "model": "old-model"}
        current = review_draft("main")
        self.record.source.update(previous_recognition=previous, review_draft=current)
        self.record.model = "current-model"
        self.record.save(update_fields=["source", "model", "updated_at"])
        restored = self.send("restore-review")
        self.assertEqual(restored.status_code, 200, restored.data)
        self.assertEqual(restored.data["data"]["result"], old_result)
        self.assertEqual(restored.data["data"]["active_task_key"], "second")
        self.assertEqual(restored.data["data"]["review_draft"], review_draft("second"))
        self.assertEqual(restored.data["data"]["model"], "old-model")
        self.record.refresh_from_db()
        self.assertEqual(self.record.source["previous_recognition"]["review_draft"], current)
        self.assertEqual(self.record.source["previous_recognition"]["result"], recognition_result())
        toggled = self.send("restore-review")
        self.assertEqual(toggled.status_code, 200, toggled.data)
        self.assertEqual(toggled.data["data"]["review_draft"], current)
        self.assertEqual(toggled.data["data"]["model"], "current-model")
        self.assertEqual(self.send("restore-review").status_code, 200)
        switched = self.send("select-task", {"task_key": "main"})
        self.assertEqual(switched.status_code, 200, switched.data)
        self.assertEqual(switched.data["data"]["review_draft"], review_draft("main"))

    def test_mapping_lock_blocks_review_switch_restore_and_creation_without_losing_draft(self):
        self.record.source.update(mapping_started_at=timezone.now().isoformat(), review_draft=review_draft(),
                                  previous_recognition={"result": recognition_result()})
        self.record.save(update_fields=["source", "updated_at"])
        original = deepcopy(self.record.source)
        for method, action, data in [
            ("patch", "", review_draft()), ("post", "select-task", {"task_key": "second"}),
            ("post", "restore-review", {}),
            ("post", "create-task", {"task_key": "main", "payload": {"task_number": "blocked"}}),
        ]:
            with self.subTest(action=action):
                response = self.send(action, data, method=method)
                self.assertEqual(response.status_code, 409, response.data)
        self.record.refresh_from_db()
        self.assertEqual(self.record.source, original)

    def test_task_creation_is_idempotent_per_selected_task_and_keeps_unknown_values_null(self):
        count = ProductionTask.objects.count()
        task_ids = {}
        for key, product_key in (("main", "product-1"), ("second", "product-2")):
            if key != "main":
                self.assertEqual(self.send("select-task", {"task_key": key}).status_code, 200)
            body = {"task_key": key, "payload": self.unknown_payload(product_key=product_key)}
            created = self.send("create-task", body)
            self.assertEqual(created.status_code, 200, created.data)
            self.assertFalse(created.data["replay"])
            task_id = created.data["data"]["task_id"]
            task_ids[key] = task_id
            task = ProductionTask.objects.get(pk=task_id)
            line = task.products.get()
            for value in (task.currency_id, task.includes_tax, task.freight_amount, task.other_fee_amount,
                          line.currency_id, line.unit_price, line.exchange_rate, line.total_amount, line.details.get().is_selected):
                self.assertIsNone(value)
            self.assertEqual(created.data["data"]["task_products"][0]["client_key"], product_key)
            replay = self.send("create-task", body, etag=created["ETag"])
            self.assertEqual(replay.status_code, 200, replay.data)
            self.assertTrue(replay.data["replay"])
            self.assertEqual(replay.data["data"]["task_id"], task_id)
            self.assertEqual(replay["ETag"], created["ETag"])
        self.assertNotEqual(task_ids["main"], task_ids["second"])
        self.assertEqual(ProductionTask.objects.count(), count + 2)
        selected = self.send("select-task", {"task_key": "main"})
        self.assertEqual(selected.data["data"]["task_id"], task_ids["main"])
        self.assertEqual(selected.data["data"]["task_products"][0]["client_key"], "product-1")

    def test_bom_creation_checks_pmc_state_is_idempotent_and_record_delete_keeps_business_data(self):
        created = self.send("create-task", {"task_key": "main", "payload": self.payload()})
        self.assertEqual(created.status_code, 200, created.data)
        task = ProductionTask.objects.get(pk=created.data["data"]["task_id"])
        sections = [{"title": title, "section_type": kind, "lines": []} for title, kind in FIXED_BOM_SECTIONS]
        body = {"task_key": "main", "plans": [{"production_task_product_id": str(task.products.get().pk), "sections": sections}]}
        denied = self.send("create-boms", body)
        self.assertEqual(denied.status_code, 409, denied.data)
        # 此处只预置 PMC 状态，测试不声称覆盖实际 PMC 确认流程。
        task.status = ProductionTaskStatus.READY
        task.save(update_fields=["status", "updated_at"])
        before = Bom.objects.count()
        result = self.send("create-boms", body)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertFalse(result.data["replay"])
        bom_id = result.data["data"]["bom_ids"][0]
        self.assertEqual(Bom.objects.count(), before + 1)
        self.assertEqual(Bom.objects.get(pk=bom_id).sections.count(), len(FIXED_BOM_SECTIONS))
        replay = self.send("create-boms", body, etag=result["ETag"])
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertTrue(replay.data["replay"])
        self.assertEqual(replay.data["data"]["bom_ids"], result.data["data"]["bom_ids"])
        self.assertEqual(Bom.objects.count(), before + 1)
        self.assertEqual(self.send("select-task", {"task_key": "second"}).status_code, 200)
        self.record.refresh_from_db()
        self.record.source["previous_recognition"] = {"result": recognition_result()}
        self.record.save(update_fields=["source", "updated_at"])
        for action in ("restore-review", "remap"):
            blocked = self.send(action)
            self.assertEqual(blocked.status_code, 409, blocked.data)
        deleted = self.send(method="delete")
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(AiProductionImport.objects.filter(pk=self.record.pk).exists())
        self.assertTrue(ProductionTask.objects.filter(pk=task.pk).exists())
        self.assertTrue(Bom.objects.filter(pk=bom_id).exists())
