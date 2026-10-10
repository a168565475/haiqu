from django.utils import timezone
from rest_framework.test import APITestCase

from apps.quotations.models import Quotation, QuotationLine, QuotationVersion
from apps.customers.models import CustomerTransactionEntity
from ..models import Inquiry
from . import test_inquiry_api


class InquiryQuotationPresenceTests(APITestCase):
    setUp = test_inquiry_api.InquiryApiTests.setUp
    create_customer = test_inquiry_api.InquiryApiTests.create_customer
    inquiry_payload = test_inquiry_api.InquiryApiTests.inquiry_payload
    create_inquiry = test_inquiry_api.InquiryApiTests.create_inquiry

    def quotation(self, inquiry_id, suffix, status="DRAFT", **kwargs):
        inquiry = Inquiry.objects.get(pk=inquiry_id)
        entity = self.entity if inquiry.customer_account_id == self.customer.pk else CustomerTransactionEntity.objects.create(customer_account=inquiry.customer_account, entity_code=f"ENTITY-{suffix}", legal_name="测试主体")
        quote = Quotation.objects.create(
            source_inquiry_id=inquiry_id, customer_account=inquiry.customer_account,
            transaction_entity=entity, owner_employee=self.employee,
            quotation_number=f"QUOTE-PRESENCE-{suffix}", subject="统计测试", **kwargs,
        )
        version = QuotationVersion.objects.create(
            quotation=quote, version_number=1, status="DRAFT", currency_code="USD",
            transaction_entity_snapshot={"legal_name": "测试主体"}, address_snapshot={"address_line1": "测试地址"},
            contact_snapshot={"display_name": "测试联系人"},
        )
        QuotationLine.objects.create(
            quotation_version=version, line_number=1, product_description_snapshot="测试产品",
            quantity="1.0000", unit_code="PCS", unit_price="1.0000", line_total="1.0000",
        )
        if status != "DRAFT":
            version.status = status
            version.locked_at = timezone.now()
            version.save(update_fields=["status", "locked_at"])
        return quote, version

    def test_drafts_count_once_and_cancelled_archived_void_only_do_not_count(self):
        draft = self.create_inquiry().data["data"]["id"]
        self.quotation(draft, "A")
        self.quotation(draft, "B", status="SENT")
        for suffix, kwargs, version_status in [
            ("C", {"outcome_status": "CANCELLED"}, "DRAFT"),
            ("D", {"archived_at": timezone.now()}, "DRAFT"),
            ("E", {}, "VOID"),
        ]:
            inquiry_id = self.create_inquiry().data["data"]["id"]
            self.quotation(inquiry_id, suffix, status=version_status, **kwargs)
        self.create_inquiry()
        listing = self.client.get("/api/v1/inquiries/", {"has_quotation": "true"})
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data["meta"]["total"], 1)
        self.assertEqual(listing.data["data"][0]["id"], draft)
        self.assertTrue(listing.data["data"][0]["has_quotation"])
        self.assertEqual(self.client.get("/api/v1/inquiries/", {"has_quotation": "false"}).data["meta"]["total"], 4)
        self.assertEqual(self.client.get("/api/v1/inquiries/metrics/").data["data"]["has_quotation"], 1)
        self.assertEqual(self.client.get("/api/v1/inquiries/", {"has_quotation": "invalid"}).status_code, 400)

    def test_cancel_and_archive_remove_count_and_foreign_customer_never_leaks(self):
        inquiry_id = self.create_inquiry().data["data"]["id"]
        quote, version = self.quotation(inquiry_id, "LIVE")
        self.assertEqual(self.client.get("/api/v1/inquiries/metrics/").data["data"]["has_quotation"], 1)
        quote.outcome_status = "CANCELLED"; quote.save(update_fields=["outcome_status"])
        self.assertEqual(self.client.get("/api/v1/inquiries/metrics/").data["data"]["has_quotation"], 0)
        quote.outcome_status = "OPEN"; quote.save(update_fields=["outcome_status"])
        Inquiry.objects.filter(pk=inquiry_id).update(archived_at=timezone.now())
        self.assertEqual(self.client.get("/api/v1/inquiries/", {"has_quotation": "true"}).data["meta"]["total"], 0)
        hidden = Inquiry.objects.create(customer_account=self.other_customer, inquiry_number="INQ-HIDDEN-QUOTE", subject="隐藏", received_at=timezone.now())
        self.quotation(hidden.pk, "HIDDEN")
        self.assertEqual(self.client.get("/api/v1/inquiries/metrics/").data["data"]["has_quotation"], 0)
        response = self.client.get("/api/v1/inquiries/export/", {"has_quotation": "true"})
        self.assertNotIn("INQ-HIDDEN-QUOTE", response.content.decode("utf-8-sig"))
