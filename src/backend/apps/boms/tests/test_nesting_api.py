import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.reference_data.models import Currency
from apps.boms.models import Bom, BomLine, BomSection
from apps.boms.nesting_models import BomNestingJob


@override_settings(FILE_VIRUS_SCAN_ENABLED=False, SALES_ACCESS_ENABLED=False,
                   MODULE_ACCESS_ENABLED=False, CONFIRMED_ROLE_POLICY_ENABLED=False)
class NestingApiTests(APITestCase):
    def setUp(self):
        # 调用方登记根目录；测试只清理在此根目录创建的独占子目录。
        root = Path(settings.BOM_NESTING_ROOT)
        root.mkdir(parents=True, exist_ok=True)
        self.temp = TemporaryDirectory(prefix="api-", dir=root)
        self.addCleanup(self.temp.cleanup)
        self.override = override_settings(BOM_NESTING_ROOT=self.temp.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.user = get_user_model().objects.create_user(username="nesting_user")
        self.employee = Employee.objects.create(user=self.user, employee_code="NESTING", display_name="排料测试")
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label="boms",
            codename__in=["change_bom", "view_all_bom"]))
        currency, _ = Currency.objects.get_or_create(code="CNY", defaults={"numeric_code": "156", "chinese_name": "人民币"})
        today = timezone.localdate()
        task = ProductionTask.objects.create(task_number="NEST-TEST", contract_number="NEST-TEST",
            order_source="NEW", order_number="NEST-TEST", order_date=today, delivery_date=today,
            salesperson=self.employee, currency=currency, includes_tax=False, order_tolerance_percent=0,
            is_repeat_order=False, preproduction_sample_required=False, delivery_method="SPLIT")
        product = ProductionTaskProduct.objects.create(production_task=task, line_number=1,
            product_name_snapshot="排料测试产品", specification_snapshot="测试", quantity=1,
            currency=currency, unit_price=0, total_amount=0, exchange_rate=1)
        self.bom = Bom.objects.create(bom_number="NEST-TEST", production_task=task, product_line=product,
            creation_method="BLANK", product_number_snapshot="TEST", product_name_snapshot="测试",
            specification_snapshot="测试", order_quantity=1)
        section = BomSection.objects.create(bom=self.bom, line_number=1, section_type="FABRIC", title="面料类")
        self.line = BomLine.objects.create(section=section, line_number=1, part_name="测试面料", unit="米", unit_consumption="2")
        self.url = f"/api/v1/boms/{self.bom.pk}/nesting-jobs/"
        self.client.force_authenticate(self.user)

    def upload(self, **overrides):
        data = {"file": SimpleUploadedFile("裁片.dxf", b"0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n"),
                "line_id": str(self.line.pk), "source_unit": "mm",
                "target_snapshot": json.dumps({"unit": "米", "part_name": "测试面料"})}
        data.update(overrides)
        return self.client.post(self.url, data, format="multipart", HTTP_IF_MATCH=etag_for_instance(self.bom))

    def test_upload_preserves_bom_and_uses_private_source(self):
        previous = self.bom.updated_at
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.data)
        job = BomNestingJob.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(job.status, "QUEUED")
        self.assertEqual(response["ETag"], etag_for_instance(job))
        self.assertNotEqual(response["ETag"], etag_for_instance(self.bom))
        self.assertTrue((Path(self.temp.name) / str(job.pk) / "source.dxf").is_file())
        self.bom.refresh_from_db()
        self.line.refresh_from_db()
        self.assertEqual(self.bom.updated_at, previous)
        self.assertEqual(self.line.unit_consumption, "2")

    def test_upload_requires_etag_and_permission(self):
        response = self.client.post(self.url, {"file": SimpleUploadedFile("x.dxf", b"0\nEOF\n"),
            "line_id": str(self.line.pk), "target_snapshot": '{"unit":"米"}'}, format="multipart")
        self.assertEqual(response.status_code, 428)
        self.user.user_permissions.clear()
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.assertEqual(self.upload().status_code, 403)

    def test_cross_bom_line_semifinished_and_non_meter_are_rejected(self):
        self.assertEqual(self.upload(line_id=str(uuid4())).status_code, 404)
        self.line.section.title = "裁剪明细"
        self.line.section.save()
        self.assertEqual(self.upload().status_code, 400)
        self.line.section.title = "面料类"
        self.line.section.save()
        self.line.unit = "套"
        self.line.save()
        self.assertEqual(self.upload().status_code, 400)
        self.assertFalse(BomNestingJob.objects.exists())

    def test_draft_is_private_even_for_another_bom_editor(self):
        response = self.upload(line_id="", draft_key=str(uuid4()))
        self.assertEqual(response.status_code, 201, response.data)
        job_id = response.data["data"]["id"]
        other = get_user_model().objects.create_user(username="nesting_other")
        Employee.objects.create(user=other, employee_code="NESTING2", display_name="另一个编辑者")
        other.user_permissions.set(self.user.user_permissions.all())
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get(f"{self.url}{job_id}/").status_code, 404)

    def test_queue_calculate_then_cancel_blocks_result_download(self):
        job = BomNestingJob.objects.get(pk=self.upload().data["data"]["id"])
        job.status, job.analysis = "NEEDS_PARAMETERS", {"pieces": [{"id": "p1"}]}
        job.analysis_digest = 'a' * 64
        job.save()
        payload = {"width_mm": 1500, "gap_mm": 0, "set_count": 2, "products_per_set": 1,
                   "pieces": [{"piece_id": "p1", "quantity": 1, "rotation_mode": "half_turn"}]}
        response = self.client.post(f"{self.url}{job.pk}/calculate/", payload, format="json", HTTP_IF_MATCH=etag_for_instance(job))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["phase"], "NEST")
        old_etag = etag_for_instance(job)
        self.assertEqual(self.client.post(f"{self.url}{job.pk}/cancel/", {}, format="json", HTTP_IF_MATCH=old_etag).status_code, 412)
        job.refresh_from_db()
        response = self.client.post(f"{self.url}{job.pk}/cancel/", {}, format="json", HTTP_IF_MATCH=etag_for_instance(job))
        self.assertEqual(response.data["data"]["status"], "CANCELED")
        self.assertEqual(self.client.get(f"{self.url}{job.pk}/preview/").status_code, 409)

    def test_rejects_incomplete_piece_counts_and_over_limit(self):
        job = BomNestingJob.objects.get(pk=self.upload().data["data"]["id"])
        job.status, job.analysis = "NEEDS_PARAMETERS", {"pieces": [{"id": "p1"}, {"id": "p2"}]}
        job.analysis_digest = 'a' * 64
        job.save()
        payload = {"width_mm": 1500, "gap_mm": 0, "set_count": 1, "products_per_set": 1,
                   "pieces": [{"piece_id": "p1", "quantity": 1, "rotation_mode": "fixed"}]}
        response = self.client.post(f"{self.url}{job.pk}/calculate/", payload, format="json", HTTP_IF_MATCH=etag_for_instance(job))
        self.assertEqual(response.status_code, 400)
        payload["pieces"].append({"piece_id": "p2", "quantity": 160, "rotation_mode": "fixed"})
        self.assertEqual(self.client.post(f"{self.url}{job.pk}/calculate/", payload, format="json", HTTP_IF_MATCH=etag_for_instance(job)).status_code, 400)

    def test_authenticated_session_still_requires_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(self.url, {"file": SimpleUploadedFile("x.dxf", b"0\nEOF\n"),
            "line_id": str(self.line.pk), "target_snapshot": '{"unit":"米"}'}, format="multipart",
            HTTP_IF_MATCH=etag_for_instance(self.bom))
        self.assertEqual(response.status_code, 403)

    @override_settings(FILE_VIRUS_SCAN_ENABLED=True)
    def test_scan_failure_leaves_no_job_or_source(self):
        from apps.imports.security import ScannerUnavailable
        with patch("apps.boms.nesting_storage.scan_upload", side_effect=ScannerUnavailable()):
            response = self.upload()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(BomNestingJob.objects.exists())
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def save_new_fabric(self, client_key):
        from . import test_bom_api as fixtures
        sections = fixtures.BomApiTests.fixed_sections([{
            "id": str(self.line.section_id), "section_type": "FABRIC", "title": "面料类",
            "lines": [{"client_key": str(client_key), "part_name": "新增面料", "unit": "米", "unit_consumption": "0.1235"}],
        }])
        return self.client.patch(f"/api/v1/boms/{self.bom.pk}/", {"sections": sections}, format="json",
                                 HTTP_IF_MATCH=etag_for_instance(self.bom))

    def test_bom_save_binds_new_fabric_jobs_and_history_survives_reload(self):
        draft_key = uuid4()
        response = self.upload(line_id="", draft_key=str(draft_key))
        self.assertEqual(response.status_code, 201, response.data)
        job = BomNestingJob.objects.get(pk=response.data["data"]["id"])
        saved = self.save_new_fabric(draft_key)
        self.assertEqual(saved.status_code, 200, saved.data)
        line = BomLine.objects.get(section__bom=self.bom, part_name="新增面料")
        job.refresh_from_db()
        self.assertEqual(job.line_id, line.pk)
        self.assertIsNone(job.draft_key)
        self.assertEqual(line.unit_consumption, "0.1235")
        history = self.client.get(self.url, {"line_id": str(line.pk)})
        self.assertEqual([entry["id"] for entry in history.data["data"]], [str(job.pk)])

    def test_bom_save_does_not_bind_another_users_same_draft_key(self):
        draft_key = uuid4()
        response = self.upload(line_id="", draft_key=str(draft_key))
        job = BomNestingJob.objects.get(pk=response.data["data"]["id"])
        other = get_user_model().objects.create_user(username="nesting_private_owner")
        job.owner_user = other
        job.save()
        saved = self.save_new_fabric(draft_key)
        self.assertEqual(saved.status_code, 200, saved.data)
        job.refresh_from_db()
        self.assertIsNone(job.line_id)
        self.assertEqual(job.draft_key, draft_key)

    def test_failed_bom_save_rolls_back_job_binding(self):
        draft_key = uuid4()
        response = self.upload(line_id="", draft_key=str(draft_key))
        job = BomNestingJob.objects.get(pk=response.data["data"]["id"])
        with patch("apps.boms.services.write_audit_log", side_effect=RuntimeError("test rollback")):
            with self.assertRaisesMessage(RuntimeError, "test rollback"):
                self.save_new_fabric(draft_key)
        job.refresh_from_db()
        self.assertIsNone(job.line_id)
        self.assertEqual(job.draft_key, draft_key)
        self.assertFalse(BomLine.objects.filter(section__bom=self.bom, part_name="新增面料").exists())

    def test_binding_ignores_other_bom_and_non_meter_target(self):
        from apps.boms.nesting_services import bind_draft_jobs
        draft_key = uuid4()
        response = self.upload(line_id="", draft_key=str(draft_key))
        job = BomNestingJob.objects.get(pk=response.data["data"]["id"])
        other_bom = Bom.objects.create(bom_number="NEST-OTHER", production_task=self.bom.production_task,
            product_line=self.bom.product_line, version_number=2, creation_method="BLANK",
            product_number_snapshot="TEST", product_name_snapshot="测试", specification_snapshot="测试", order_quantity=1)
        job.bom = other_bom
        job.save()
        bind_draft_jobs(bom=self.bom, owner_user=self.user, new_lines_by_client_key={draft_key: self.line})
        job.refresh_from_db()
        self.assertIsNone(job.line_id)
        job.bom = self.bom
        job.save()
        self.line.unit = "套"
        self.line.save()
        bind_draft_jobs(bom=self.bom, owner_user=self.user, new_lines_by_client_key={draft_key: self.line})
        job.refresh_from_db()
        self.assertIsNone(job.line_id)
        self.assertEqual(job.draft_key, draft_key)
