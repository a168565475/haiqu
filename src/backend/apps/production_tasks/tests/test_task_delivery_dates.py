from datetime import timedelta
from uuid import uuid4

from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.boms.models import Bom, BomCreationMethod, BomStatus

from ..models import ProductionTask, ProductionTaskStatus
from . import test_production_task_api as fixtures


class ProductionTaskDeliveryDateTests(APITestCase):
    def setUp(self):
        fixtures.ProductionTaskApiTests.setUp(self)
        from apps.reference_data.models import Currency
        self.currency = Currency.objects.get(code="CNY")
    payload = fixtures.ProductionTaskApiTests.payload
    create_task = fixtures.ProductionTaskApiTests.create_task

    def make_task(self):
        today = timezone.localdate()
        created = self.create_task(
            delivery_date=(today + timedelta(days=30)).isoformat(),
            delivery_method="SPLIT",
            delivery_batches=[
                {"quantity": "6", "delivery_date": (today + timedelta(days=20)).isoformat(), "note": "保留首批备注"},
                {"quantity": "4", "delivery_date": (today + timedelta(days=30)).isoformat(), "note": "保留末批备注"},
            ],
        )
        task = ProductionTask.objects.get(pk=created.data["data"]["id"])
        return task, f"/api/v1/production-tasks/{task.pk}/"

    def patch_dates(self, url, data, **headers):
        headers.setdefault("HTTP_IF_MATCH", self.client.get(url)["ETag"])
        return self.client.patch(url, data, format="json", **headers)

    def test_legacy_products_and_bom_survive_date_patch_and_reconfirmation(self):
        task, url = self.make_task()
        product = task.products.get()
        product.product_color = None
        product.color_code_snapshot = ""
        product.save()
        product.details.all().delete()
        bom = Bom.objects.create(
            bom_number="BOM-DATE-PRESERVE-001", production_task=task,
            product_line=product, creation_method=BomCreationMethod.BLANK,
            order_quantity=product.quantity, created_by_employee=self.employee,
            status=BomStatus.VERIFIED,
        )
        products_before = list(task.products.values())
        bom_before = Bom.objects.filter(pk=bom.pk).values().get()
        batches_before = list(task.delivery_batches.values())
        task.status = ProductionTaskStatus.READY
        task.save()
        new_date = (timezone.localdate() + timedelta(days=15)).isoformat()
        response = self.patch_dates(url, {
            "delivery_date": new_date,
            "delivery_batch_dates": [{"id": str(row["id"]), "delivery_date": new_date} for row in batches_before],
        })
        self.assertEqual(response.status_code, 200, response.data)
        task.refresh_from_db()
        self.assertEqual(task.status, ProductionTaskStatus.DRAFT)
        self.assertEqual(task.delivery_date.isoformat(), new_date)
        self.assertEqual(list(task.products.values()), products_before)
        self.assertEqual(Bom.objects.filter(pk=bom.pk).values().get(), bom_before)
        for before, after in zip(batches_before, task.delivery_batches.values()):
            self.assertEqual(after["delivery_date"].isoformat(), new_date)
            for key in set(before) - {"delivery_date", "updated_at"}:
                self.assertEqual(after[key], before[key], key)
        audit = AuditLog.objects.get(object_id=task.pk, action="UPDATED")
        self.assertEqual(audit.before_data["delivery_date"], (timezone.localdate() + timedelta(days=30)).isoformat())
        self.assertEqual(audit.after_data["delivery_date"], new_date)
        self.assertEqual(audit.before_data["delivery_batches"][0]["id"], str(batches_before[0]["id"]))
        self.assertEqual(audit.after_data["delivery_batches"][0]["delivery_date"], new_date)
        submitted = self.client.post(url + "submit/", {}, format="json", HTTP_IF_MATCH=response["ETag"])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        confirmed = self.client.post(url + "pmc-decision/", {
            "follower_ids": [str(self.follower.pk)], "tax_rate": 3,
            "decision": "CONFIRM", "planned_start_date": timezone.localdate().isoformat(),
            "planned_end_date": (timezone.localdate() + timedelta(days=14)).isoformat(),
        }, format="json", HTTP_IF_MATCH=submitted["ETag"])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data["data"]["status"], ProductionTaskStatus.READY)
        self.assertEqual(list(task.products.values()), products_before)
        self.assertEqual(Bom.objects.filter(pk=bom.pk).values().get(), bom_before)

    def test_batch_only_changes_one_date_and_preserves_head_and_other_batch(self):
        task, url = self.make_task()
        first, second = list(task.delivery_batches.all())
        second_before = task.delivery_batches.filter(pk=second.pk).values().get()
        old_head = task.delivery_date
        response = self.patch_dates(url, {"delivery_batch_dates": [
            {"id": str(first.pk), "delivery_date": (timezone.localdate() + timedelta(days=10)).isoformat()},
        ]})
        self.assertEqual(response.status_code, 200, response.data)
        task.refresh_from_db()
        self.assertEqual(task.delivery_date, old_head)
        self.assertEqual(task.delivery_batches.filter(pk=second.pk).values().get(), second_before)

    def test_invalid_items_are_rejected_without_mutation(self):
        task, url = self.make_task()
        other, _ = self.make_task()
        batch = task.delivery_batches.first()
        valid = {"id": str(batch.pk), "delivery_date": (timezone.localdate() + timedelta(days=10)).isoformat()}
        invalid_items = [
            [], [{}], [{"id": str(batch.pk)}], [{"delivery_date": valid["delivery_date"]}],
            [None], ["invalid"], [{**valid, "id": "bad-uuid"}],
            [{**valid, "delivery_date": "bad-date"}], [{**valid, "delivery_date": None}],
            [{**valid, "quantity": 999}], [{**valid, "note": "不可改备注"}],
            [valid, valid], [valid, {**valid, "id": str(uuid4())}],
            [valid, {**valid, "id": str(other.delivery_batches.first().pk)}],
            [{**valid, "delivery_date": (timezone.localdate() - timedelta(days=1)).isoformat()}],
        ]
        before = ProductionTask.objects.filter(pk=task.pk).values().get()
        batches = list(task.delivery_batches.values())
        audit_count = AuditLog.objects.count()
        for items in invalid_items:
            with self.subTest(items=items):
                response = self.patch_dates(url, {"delivery_batch_dates": items})
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(ProductionTask.objects.filter(pk=task.pk).values().get(), before)
                self.assertEqual(list(task.delivery_batches.values()), batches)
                self.assertEqual(AuditLog.objects.count(), audit_count)

    def test_date_patch_cannot_mix_other_fields_or_replace_batches(self):
        task, url = self.make_task()
        updates = [{"id": str(task.delivery_batches.first().pk), "delivery_date": (timezone.localdate() + timedelta(days=10)).isoformat()}]
        for extra in ({"follower_ids": []}, {"special_requirements_html": "改资料"},
                      {"bom_sync_mode": "KEEP"}, {"delivery_batches": []}, {"products": []}):
            with self.subTest(extra=extra):
                response = self.patch_dates(url, {"delivery_batch_dates": updates, **extra})
                self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(AuditLog.objects.filter(object_id=task.pk, action="UPDATED").exists())

    def test_noop_rejected_without_resetting_ready_status(self):
        task, url = self.make_task()
        task.status = ProductionTaskStatus.READY
        task.save()
        batch = task.delivery_batches.first()
        response = self.patch_dates(url, {"delivery_batch_dates": [
            {"id": str(batch.pk), "delivery_date": batch.delivery_date.isoformat()},
        ]})
        self.assertEqual(response.status_code, 400, response.data)
        task.refresh_from_db()
        self.assertEqual(task.status, ProductionTaskStatus.READY)

    def test_etag_and_historical_status_gates(self):
        task, url = self.make_task()
        data = {"delivery_batch_dates": [{"id": str(task.delivery_batches.first().pk),
                "delivery_date": (timezone.localdate() + timedelta(days=10)).isoformat()}]}
        self.assertEqual(self.client.patch(url, data, format="json").status_code, 428)
        self.assertEqual(self.patch_dates(url, data, HTTP_IF_MATCH='"outdated"').status_code, 412)
        for status in (ProductionTaskStatus.COMPLETED, ProductionTaskStatus.CANCELLED):
            task.status = status
            task.save()
            response = self.patch_dates(url, data)
            self.assertEqual(response.status_code, 409, response.data)

    def test_change_permission_is_required(self):
        task, url = self.make_task()
        etag = self.client.get(url)["ETag"]
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label="production_tasks", codename="change_productiontask"))
        for cache in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            self.user.__dict__.pop(cache, None)
        response = self.client.patch(url, {"delivery_batch_dates": [{"id": str(task.delivery_batches.first().pk),
            "delivery_date": (timezone.localdate() + timedelta(days=10)).isoformat()}]}, format="json", HTTP_IF_MATCH=etag)
        self.assertEqual(response.status_code, 403, response.data)
