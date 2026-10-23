from types import SimpleNamespace

from django.test import TestCase, override_settings
from rest_framework.exceptions import PermissionDenied

from apps.access_control.sales_sources import readable_files, require_file
from apps.files.reference_guards import require_non_finance_receipt_file
from apps.crm import services as crm
from apps.inquiries import services as inquiries
from apps.quotations import services as quotations
from apps.sales_orders import services as orders
from apps.samples import services as samples
from .receipt_fixtures import ReceiptFixtureMixin


class ReceiptFileBoundaryTests(ReceiptFixtureMixin, TestCase):
    def test_policy_disabled_and_admin_cannot_reuse_finance_file(self):
        file = self.file(); ordinary = self.file(storage_key="inquiries/ordinary.png")
        request = SimpleNamespace(user=self.user, employee=self.actor)
        for enabled, admin in ((False, False), (False, True), (True, True)):
            with self.subTest(enabled=enabled, admin=admin), override_settings(SALES_ACCESS_ENABLED=enabled):
                self.user.is_superuser = admin
                with self.assertRaises(PermissionDenied): require_file(request, file)
                self.assertFalse(readable_files(request).filter(pk=file.pk).exists())
                self.assertTrue(readable_files(request).filter(pk=ordinary.pk).exists())
                require_file(request, ordinary)

    def test_direct_service_objects_rejected_before_binding(self):
        file = self.file()
        self.user.is_superuser = True
        request = SimpleNamespace(user=self.user, employee=self.actor)
        common = {"actor_employee": self.actor, "request": request}
        calls = [
            lambda: orders._line_identity({"product_image": file}, None, None),
            lambda: orders._line_identity({}, None, SimpleNamespace(product_image=file)),
            lambda: orders._replace_children(None, [], [], [file], self.actor),
            lambda: orders.change_confirmed_sales_order(order=None, validated_data={"order": {"evidence_files": [file]}}, **common),
            lambda: orders.set_sales_order_line_product_image(order=None, line=None, business_file=file, **common),
            lambda: orders.cancel_delivery_batch(order=None, delivery_batch=None, reason="隔离", evidence_file=file, **common),
            lambda: quotations.register_formal_document(version=None, business_file=file, **common),
            lambda: quotations.dispatch_version(version=None, validated_data={"evidence_file": file}, **common),
            lambda: quotations.set_line_product_image(line=None, business_file=file, **common),
            lambda: crm.create_communication(validated_data={"business_files": [file]}, **common),
            lambda: inquiries.link_inquiry_file(inquiry=None, business_file=file, file_role="OTHER", **common),
            lambda: inquiries.set_inquiry_item_product_image(item=None, business_file=file, **common),
            lambda: samples.link_sample_file(sample_request=None, business_file=file, file_role="OTHER", **common),
            lambda: samples.confirm_sample_finance(sample_request=None, note="隔离", business_file=file, **common),
            lambda: samples.upload_sample_parameters(sample_request=None, parameter_type="METAL", note="隔离", business_file=file, **common),
        ]
        with override_settings(SALES_ACCESS_ENABLED=False):
            for index, invoke in enumerate(calls):
                with self.subTest(entry=index), self.assertRaises(PermissionDenied): invoke()

    def test_non_finance_image_identity_keeps_existing_flow(self):
        file = self.file(storage_key="sales-orders/ordinary.png")
        require_non_finance_receipt_file(file); require_non_finance_receipt_file(None)
        identity = orders._line_identity({"product_image": file, "customer_product_name_snapshot": "原流程产品",
            "customer_specification_snapshot": "原流程规格"}, None, None)
        self.assertEqual(identity["product_image"], file)
        self.assertEqual(identity["product_name_snapshot"], "原流程产品")
