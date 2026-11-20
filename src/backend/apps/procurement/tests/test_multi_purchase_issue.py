from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.inventory.models import PublicStockBalance, PublicStockMovement
from apps.material_issues.tests import test_catalog_issue_api as catalog_issues
from apps.organizations.models import Employee
from apps.production_scheduling.services import create_schedule
from apps.workshop_config.models import Craft, Workshop
from apps.workshop_config.tests.factories import production_employee

from .test_multi_product_purchase import MultiProductPurchaseFixture


@override_settings(PUBLIC_STOCK_ISSUES_ENABLED=True)
class CombinedPurchaseProductIssueTests(MultiProductPurchaseFixture, APITestCase):
    issue = catalog_issues.CatalogIssueApiTests.issue

    def test_single_receipt_two_products_draw_from_same_stock_and_record_their_own_bom(self):
        for line in (self.red_screw, self.blue_screw):
            line.section.title = "五金件"
            line.section.save(update_fields=["title"])
        self.create_group()
        self.receive(self.batch("1500"), "1500")
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label="material_issues"))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        reviewer = get_user_model().objects.create_user(username="combined_receipt_reviewer")
        Employee.objects.create(user=reviewer, employee_code="COMBINED_ISSUE_REVIEW", display_name="审核员")
        reviewer.user_permissions.set(self.user.user_permissions.all())
        self.reviewer_client = APIClient()
        self.reviewer_client.force_authenticate(reviewer)
        workshop, _ = Workshop.objects.get_or_create(name="金工车间")
        recipient = production_employee(workshop=workshop, position="领料员", name="合并采购领料员")
        craft = Craft.objects.create(craft_type="INTERNAL", name="合并采购领料金工作业", workshop=workshop, plan_category="METAL")
        today = timezone.localdate()
        schedule = create_schedule(validated_data={
            "client_request_id": uuid4(), "production_task_id": self.task.pk, "source_revision_hash": "",
            "items": [{"product_line_id": product.pk, "planned_quantity": product.quantity, "craft_ids": {craft.pk},
                       "material_inbound_date": today, "metal_return_date": today, "sewing_return_date": today,
                       "finished_inbound_date": today} for product in (self.red, self.blue)],
        }, actor_employee=self.employee)
        for product, bom_line, quantity, remaining in (
            (self.red, self.red_screw, 1100, 400), (self.blue, self.blue_screw, 400, 0),
        ):
            scope = {"production_task_id": str(self.task.pk), "product_line_id": str(product.pk),
                     "workshop_id": str(workshop.pk)}
            candidates = self.client.get("/api/v1/material-issues/requirements/", scope)
            self.assertEqual(candidates.status_code, 200, candidates.data)
            requirement, = candidates.data["data"]["items"]
            created = self.client.post("/api/v1/material-issues/", {
                **scope, "client_request_id": str(uuid4()), "plan_category": "METAL",
                "schedule_product_id": str(schedule.products.get(product_line=product).pk),
                "recipient_workshop_employee_id": str(recipient.pk), "issue_at": timezone.now().isoformat(),
                "lines": [{"requirement_id": requirement["requirement_id"], "requested_quantity": str(quantity)}],
            }, format="json")
            self.assertEqual(created.status_code, 201, created.data)
            issued, _ = self.issue(created)
            balance = PublicStockBalance.objects.get()
            movement = PublicStockMovement.objects.get(source_type="MATERIAL_ISSUE", source_id=issued.pk)
            self.assertEqual((movement.balance_id, movement.product_line_id, movement.bom_line_id, movement.quantity),
                             (balance.pk, product.pk, bom_line.pk, Decimal(quantity)))
            self.assertEqual(balance.quantity, Decimal(remaining))
