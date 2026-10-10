from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.crm.models import CustomerCommunication, CustomerTimelineEvent
from apps.customers.models import (
    CustomerAccount,
    CustomerAssignment,
    CustomerContact,
    CustomerFileLink,
    CustomerTransactionEntity,
)
from apps.files.models import BusinessFile
from apps.organizations.models import Employee
from apps.workflow.models import BusinessTask, SlaPolicy, SlaTrackingStatus
from apps.quotations.models import Quotation, QuotationLine, QuotationVersion
from apps.reference_data.models import Incoterm

from ..models import Inquiry, InquiryAssignmentHistory, InquiryDraftRevision, InquiryItem, InquiryTaskLink


class InquiryApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="inquiry_api_user")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="INQUIRY_API_USER",
            display_name="询价接口测试员工",
        )
        self.other_user = user_model.objects.create_user(username="inquiry_api_other")
        self.other_employee = Employee.objects.create(
            user=self.other_user,
            employee_code="INQUIRY_API_OTHER",
            display_name="其他询价测试员工",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(content_type__app_label__in=["inquiries", "workflow"])
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.customer = self.create_customer("INQUIRY_CUSTOMER", "询价客户", self.employee)
        self.other_customer = self.create_customer(
            "OTHER_INQUIRY_CUSTOMER",
            "其他询价客户",
            self.other_employee,
        )
        self.entity = CustomerTransactionEntity.objects.create(
            customer_account=self.customer,
            entity_code="INQUIRY_ENTITY",
            legal_name="询价交易主体",
        )
        self.contact = CustomerContact.objects.create(
            customer_account=self.customer,
            display_name="询价联系人",
        )

    def create_customer(self, code, name, owner):
        customer = CustomerAccount.objects.create(
            account_code=code,
            account_name=name,
            primary_country_code="CN",
        )
        CustomerAssignment.objects.create(
            customer_account=customer,
            employee=owner,
            assignment_role="PRIMARY_OWNER",
            effective_from=timezone.now(),
        )
        return customer

    def inquiry_payload(self, **overrides):
        payload = {
            "customer_account_id": str(self.customer.pk),
            "transaction_entity_id": str(self.entity.pk),
            "customer_contact_id": str(self.contact.pk),
            "inquiry_source": "EMAIL",
            "subject": "测试询价",
            "description": "需要核价",
            "received_at": timezone.now().isoformat(),
            "items": [
                {
                    "product_description": "测试产品",
                    "quantity": "10.0000",
                    "unit_code": "PCS",
                    "target_currency_code": "USD",
                }
            ],
        }
        payload.update(overrides)
        return payload

    def create_inquiry(self, **overrides):
        response = self.client.post("/api/v1/inquiries/", self.inquiry_payload(**overrides), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def test_create_nested_items_generates_number_audit_and_timeline(self):
        response = self.create_inquiry()
        inquiry = Inquiry.objects.get(pk=response.data["data"]["id"])

        self.assertRegex(inquiry.inquiry_number, r"^INQ-\d{6}-\d{6,}$")
        self.assertEqual(inquiry.items.get().line_number, 1)
        self.assertEqual(inquiry.status, "DRAFT")
        self.assertEqual(inquiry.owner_employee, self.employee)
        self.assertIn("ETag", response)
        self.assertTrue(
            AuditLog.objects.filter(object_type="INQUIRY", object_id=inquiry.pk, action="CREATED").exists()
        )
        self.assertTrue(
            CustomerTimelineEvent.objects.filter(
                customer_account=self.customer,
                source_id=inquiry.pk,
                event_type="INQUIRY_CREATED",
            ).exists()
        )

    def test_create_item_keeps_specification_color_and_material_separate(self):
        response = self.create_inquiry(
            items=[
                {
                    "product_description": "导演椅",
                    "specification": "57X47X78cm",
                    "color": "黑色哑光",
                    "material": "铝合金",
                    "quantity": "10.0000",
                    "unit_code": "PCS",
                    "target_currency_code": "USD",
                }
            ]
        )

        item = response.data["data"]["items"][0]
        self.assertEqual(item["specification"], "57X47X78cm")
        self.assertEqual(item["color"], "黑色哑光")
        self.assertEqual(item["material"], "铝合金")

    def test_rich_text_description_keeps_safe_formatting_and_removes_active_content(self):
        created = self.create_inquiry(
            description=(
                '<p>客户需要 <strong>蓝色帐篷</strong>。</p>'
                '<script>alert("unsafe")</script>'
                '<a href="javascript:alert(1)">危险链接</a>'
                '<a href="https://example.com/spec">安全链接</a>'
            )
        )

        description = created.data["data"]["description"]
        self.assertIn("<strong>蓝色帐篷</strong>", description)
        self.assertNotIn("script", description)
        self.assertNotIn("unsafe", description)
        self.assertNotIn("javascript:", description)
        self.assertIn('href="https://example.com/spec"', description)

    def test_rich_text_description_rejects_more_than_5000_visible_characters(self):
        rejected = self.client.post(
            "/api/v1/inquiries/",
            self.inquiry_payload(description=f"<p>{'沟' * 5001}</p>"),
            format="json",
        )

        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertIn("description", rejected.data["error"]["field_errors"])

    def test_rich_text_description_keeps_supported_formatting_and_strips_unsafe_attributes(self):
        created = self.create_inquiry(
            description=(
                '<h2 style="text-align:center" onclick="alert(1)">沟通重点</h2>'
                '<p><span style="color:#112233;font-size:18px;position:fixed">已确认</span>'
                '<mark data-color="#fef3c7" style="background-color:#fef3c7;color:inherit">高亮</mark></p>'
                '<ul data-type="taskList"><li data-type="taskItem" data-checked="true">'
                '<label><input type="checkbox" checked><span></span></label><div><p>发送报价</p></div></li></ul>'
                '<blockquote>客户要求下周回复</blockquote><pre><code>SKU-001</code></pre><hr>'
                '<h4>补充说明</h4><p>10<sup>2</sup> H<sub>2</sub>O</p>'
                '<table onclick="alert(1)"><tbody><tr><th colspan="2" style="text-align:center">规格</th>'
                '<td rowspan="2">蓝色</td></tr></tbody></table>'
                '<img src=x onerror="alert(1)"><a href="mailto:sales@example.com">邮件</a>'
            )
        )

        description = created.data["data"]["description"]
        self.assertIn('<h2 style="text-align: center">沟通重点</h2>', description)
        self.assertIn('<span style="color: #112233; font-size: 18px">已确认</span>', description)
        self.assertIn('<mark data-color="#fef3c7" style="background-color: #fef3c7">高亮</mark>', description)
        self.assertIn('<ul data-type="taskList"><li data-type="taskItem" data-checked="true">', description)
        self.assertIn('<input type="checkbox" checked="checked" disabled="disabled">', description)
        self.assertIn('<blockquote>客户要求下周回复</blockquote>', description)
        self.assertIn('<pre><code>SKU-001</code></pre><hr>', description)
        self.assertIn('<h4>补充说明</h4><p>10<sup>2</sup> H<sub>2</sub>O</p>', description)
        self.assertIn('<th colspan="2" style="text-align: center">规格</th>', description)
        self.assertIn('<td rowspan="2">蓝色</td>', description)
        self.assertIn('href="mailto:sales@example.com"', description)
        self.assertNotIn("onclick", description)
        self.assertNotIn("position", description)
        self.assertNotIn("onerror", description)
        self.assertNotIn("<img", description)

    def test_options_master_data_and_reference_code_validation(self):
        inquiry_options = self.client.get("/api/v1/inquiries/options/")
        published_sources = self.client.get(
            "/api/v1/reference-data/options/INQUIRY_SOURCE/"
        )
        currencies = self.client.get(
            "/api/v1/reference-data/currencies/?status=ACTIVE&q=USD"
        )
        incoterms = self.client.get(
            "/api/v1/reference-data/incoterms/?status=ACTIVE&page_size=100"
        )

        self.assertEqual(inquiry_options.status_code, 200, inquiry_options.data)
        self.assertEqual(currencies.status_code, 200, currencies.data)
        self.assertEqual(incoterms.status_code, 200, incoterms.data)
        self.assertSetEqual(
            {item["item_code"] for item in inquiry_options.data["data"]["sources"]},
            {item["code"] for item in published_sources.data["data"]},
        )
        self.assertIn("USD", {item["code"] for item in currencies.data["data"]})
        self.assertIn("FOB", {item["code"] for item in incoterms.data["data"]})
        self.assertEqual(
            self.client.post("/api/v1/reference-data/currencies/", {}, format="json").status_code,
            403,
        )

        created = self.create_inquiry()
        listing = self.client.get("/api/v1/inquiries/")
        source_labels = {
            item["code"]: item["label"] for item in published_sources.data["data"]
        }
        created_row = next(
            item for item in listing.data["data"]
            if item["id"] == created.data["data"]["id"]
        )
        self.assertEqual(
            created_row["source"]["display_name"],
            source_labels[created_row["source"]["code"]],
        )

        invalid_source = self.client.post(
            "/api/v1/inquiries/",
            self.inquiry_payload(inquiry_source="UNKNOWN"),
            format="json",
        )
        invalid_trade_term = self.client.post(
            "/api/v1/inquiries/",
            self.inquiry_payload(trade_term_code="ABC"),
            format="json",
        )
        invalid_item_currency = self.client.post(
            "/api/v1/inquiries/",
            self.inquiry_payload(items=[{
                "product_description": "错误币种产品",
                "quantity": "1.0000",
                "unit_code": "PCS",
                "target_currency_code": "ZZZ",
            }]),
            format="json",
        )

        self.assertEqual(invalid_source.status_code, 400, invalid_source.data)
        self.assertEqual(invalid_trade_term.status_code, 400, invalid_trade_term.data)
        self.assertEqual(invalid_item_currency.status_code, 400, invalid_item_currency.data)

    def test_unchanged_historical_incoterm_remains_editable_after_deactivation(self):
        created = self.create_inquiry(trade_term_code="FOB")
        incoterm = Incoterm.objects.get(code="FOB")
        incoterm.status = "INACTIVE"
        incoterm.save(update_fields=["status", "updated_at"])

        updated = self.client.patch(
            f"/api/v1/inquiries/{created.data['data']['id']}/",
            {"subject": "保留历史贸易术语"},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )

        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["data"]["trade_term_code"], "FOB")

    def test_cross_customer_entity_is_rejected_without_leaking_record(self):
        foreign_entity = CustomerTransactionEntity.objects.create(
            customer_account=self.other_customer,
            entity_code="FOREIGN_INQUIRY_ENTITY",
            legal_name="其他客户主体",
        )
        response = self.client.post(
            "/api/v1/inquiries/",
            self.inquiry_payload(transaction_entity_id=str(foreign_entity.pk)),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("transaction_entity_id", response.data["error"]["field_errors"])

    def test_list_does_not_leak_unassigned_customer_inquiries(self):
        visible = Inquiry.objects.create(
            customer_account=self.customer,
            owner_employee=self.employee,
            inquiry_number="VISIBLE_INQUIRY",
            subject="可见询价",
            received_at=timezone.now(),
        )
        hidden = Inquiry.objects.create(
            customer_account=self.other_customer,
            owner_employee=self.other_employee,
            inquiry_number="HIDDEN_INQUIRY",
            subject="不可见询价",
            received_at=timezone.now(),
        )

        response = self.client.get("/api/v1/inquiries/")
        returned_ids = {item["id"] for item in response.data["data"]}

        self.assertIn(str(visible.pk), returned_ids)
        self.assertNotIn(str(hidden.pk), returned_ids)

    def test_draft_update_requires_etag_and_submitted_inquiry_is_read_only(self):
        created = self.create_inquiry()
        inquiry_id = created.data["data"]["id"]
        url = f"/api/v1/inquiries/{inquiry_id}/"

        missing = self.client.patch(url, {"subject": "缺少 ETag"}, format="json")
        updated = self.client.patch(
            url,
            {"subject": "已更新标题"},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        submitted = self.client.post(
            f"{url}submit/",
            {"note": "资料完整"},
            format="json",
            HTTP_IF_MATCH=updated.headers["ETag"],
        )
        rejected = self.client.patch(
            url,
            {"subject": "提交后修改"},
            format="json",
            HTTP_IF_MATCH=submitted.headers["ETag"],
        )

        self.assertEqual(missing.status_code, 428)
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(rejected.status_code, 409, rejected.data)

    def test_inq02_atomic_draft_save_replaces_items_and_is_idempotent(self):
        created = self.create_inquiry(
            idempotency_key="inq02-create-key",
            items=[
                {
                    "product_description": "初始产品",
                    "quantity": "10.0000",
                    "unit_code": "PCS",
                    "target_currency_code": "USD",
                }
            ],
        )
        inquiry_id = created.data["data"]["id"]
        first_item = created.data["data"]["items"][0]
        payload = {
            "subject": "多行草稿",
            "customer_language_code": "EN",
            "trade_term_code": "FOB",
            "trade_term_place": "NINGBO",
            "delivery_requirement": "下单后 45 天",
            "estimated_amount_min": "30000.00",
            "estimated_amount_max": "50000.00",
            "estimated_currency_code": "USD",
            "idempotency_key": "inq02-draft-key",
            "items": [
                {
                    "id": first_item["id"],
                    "product_description": "折叠露营床",
                    "specification": "600D 牛津布",
                    "color": "深灰色",
                    "material": "涤纶",
                    "quantity": "1200.0000",
                    "unit_code": "PCS",
                    "target_unit_price": "18.5000",
                    "target_currency_code": "USD",
                    "expected_date": "2026-09-05",
                    "product_match_status": "PENDING",
                    "notes": "黑色",
                },
                {
                    "product_description": "折叠露营椅",
                    "specification": "铝管",
                    "quantity": "800.0000",
                    "unit_code": "PCS",
                    "target_unit_price": "12.2000",
                    "target_currency_code": "USD",
                    "expected_date": "2026-09-05",
                    "product_match_status": "PENDING",
                    "notes": "",
                },
            ],
        }
        saved = self.client.patch(
            f"/api/v1/inquiries/{inquiry_id}/draft/",
            payload,
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        retried = self.client.patch(
            f"/api/v1/inquiries/{inquiry_id}/draft/",
            payload,
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        detail = self.client.get(f"/api/v1/inquiries/{inquiry_id}/")

        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(retried.status_code, 200, retried.data)
        self.assertEqual(saved.data["data"]["draft_version"], 2)
        self.assertEqual(Inquiry.objects.get(pk=inquiry_id).items.count(), 2)
        self.assertEqual(InquiryDraftRevision.objects.filter(inquiry_id=inquiry_id).count(), 2)
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data["data"]["items"][0]["expected_date"], "2026-09-05")
        self.assertEqual(detail.data["data"]["items"][0]["color"], "深灰色")
        self.assertEqual(detail.data["data"]["items"][0]["material"], "涤纶")
        self.assertEqual(detail.data["data"]["trade_term_code"], "FOB")

    def test_inq02_draft_requires_current_etag_and_valid_amount_range(self):
        created = self.create_inquiry()
        inquiry_id = created.data["data"]["id"]
        invalid = self.client.patch(
            f"/api/v1/inquiries/{inquiry_id}/draft/",
            {
                "idempotency_key": "inq02-invalid-key",
                "estimated_amount_min": "100.00",
                "estimated_amount_max": "10.00",
                "estimated_currency_code": "USD",
            },
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        missing = self.client.patch(
            f"/api/v1/inquiries/{inquiry_id}/draft/",
            {"idempotency_key": "inq02-missing-key", "subject": "缺少版本"},
            format="json",
        )

        self.assertEqual(invalid.status_code, 400, invalid.data)
        self.assertEqual(missing.status_code, 428, missing.data)

    def test_item_crud_uses_parent_etag_and_locks_after_submit(self):
        created = self.create_inquiry(items=[])
        inquiry_id = created.data["data"]["id"]
        items_url = f"/api/v1/inquiries/{inquiry_id}/items/"
        added = self.client.post(
            items_url,
            {
                "product_description": "新增产品",
                "quantity": "2.0000",
                "unit_code": "PCS",
            },
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        item_id = added.data["data"]["id"]
        stale = self.client.patch(
            f"/api/v1/inquiry-items/{item_id}/",
            {"quantity": "3.0000"},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        changed = self.client.patch(
            f"/api/v1/inquiry-items/{item_id}/",
            {"quantity": "3.0000"},
            format="json",
            HTTP_IF_MATCH=added.headers["ETag"],
        )
        submitted = self.client.post(
            f"/api/v1/inquiries/{inquiry_id}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=changed.headers["ETag"],
        )
        locked = self.client.delete(
            f"/api/v1/inquiry-items/{item_id}/",
            HTTP_IF_MATCH=submitted.headers["ETag"],
        )

        self.assertEqual(added.status_code, 201, added.data)
        self.assertEqual(stale.status_code, 412, stale.data)
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(locked.status_code, 409, locked.data)

    def test_state_machine_uses_stage_sla_and_real_quotation_facts(self):
        SlaPolicy.objects.create(
            policy_code="INQUIRY_STANDARD",
            display_name="询价标准 SLA",
            target_type="INQUIRY",
            response_minutes=30,
            resolution_minutes=120,
            is_enabled=True,
        )
        created = self.create_inquiry()
        inquiry_id = created.data["data"]["id"]
        base = f"/api/v1/inquiries/{inquiry_id}/"
        submitted = self.client.post(base + "submit/", {}, format="json", HTTP_IF_MATCH=created.headers["ETag"])
        missing_note = self.client.post(
            base + "respond/", {}, format="json", HTTP_IF_MATCH=submitted.headers["ETag"]
        )
        empty_rich_note = self.client.post(
            base + "respond/",
            {"communication_type": "EMAIL", "content": "<p><br></p>", "occurred_at": timezone.now().isoformat()},
            format="json",
            HTTP_IF_MATCH=submitted.headers["ETag"],
        )
        responded = self.client.post(
            base + "respond/",
            {
                "communication_type": "EMAIL",
                "content": "<p><strong>已通过邮件回复客户</strong>，开始澄清需求。<script>alert('xss')</script></p>",
                "occurred_at": timezone.now().isoformat(),
            },
            format="json",
            HTTP_IF_MATCH=submitted.headers["ETag"],
        )
        confirmed = self.client.post(
            base + "confirm-requirements/", {}, format="json", HTTP_IF_MATCH=responded.headers["ETag"]
        )
        missing_quote = self.client.post(
            base + "sync-quotation/", {}, format="json", HTTP_IF_MATCH=confirmed.headers["ETag"]
        )
        inquiry = Inquiry.objects.get(pk=inquiry_id)
        quotation = Quotation.objects.create(
            customer_account=self.customer,
            transaction_entity=self.entity,
            source_inquiry=inquiry,
            owner_employee=self.employee,
            quotation_number="INQ03_REAL_QUOTATION",
            subject="来源询盘报价",
        )
        version = QuotationVersion.objects.create(
            quotation=quotation,
            version_number=1,
            currency_code="USD",
            transaction_entity_snapshot={"id": str(self.entity.pk), "entity_code": self.entity.entity_code},
            address_snapshot={"address_code": "TEST_ADDRESS"},
            contact_snapshot={"id": str(self.contact.pk), "display_name": self.contact.display_name},
        )
        QuotationLine.objects.create(
            quotation_version=version,
            line_number=1,
            product_description_snapshot="测试产品",
            quantity="1.0000",
            unit_code="PCS",
            unit_price="1.0000",
            line_total="1.0000",
        )
        version.status = "SENT"
        version.locked_at = timezone.now()
        version.save(update_fields=["status", "locked_at", "updated_at"])
        quoting = self.client.post(
            base + "sync-quotation/", {}, format="json", HTTP_IF_MATCH=confirmed.headers["ETag"]
        )
        quoted = self.client.post(
            base + "mark-quoted/", {}, format="json", HTTP_IF_MATCH=quoting.headers["ETag"]
        )
        followed = self.client.post(
            base + "follow-up/",
            {"communication_type": "PHONE", "content": "等待客户确认报价。", "occurred_at": timezone.now().isoformat()},
            format="json",
            HTTP_IF_MATCH=quoted.headers["ETag"],
        )
        followed_again = self.client.post(
            base + "follow-up/",
            {"communication_type": "WECHAT", "content": "客户补充了交期问题。", "occurred_at": timezone.now().isoformat()},
            format="json",
            HTTP_IF_MATCH=followed.headers["ETag"],
        )

        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(missing_note.status_code, 400, missing_note.data)
        self.assertEqual(empty_rich_note.status_code, 400, empty_rich_note.data)
        self.assertEqual(responded.status_code, 200, responded.data)
        response_audit = AuditLog.objects.get(object_type="INQUIRY", object_id=inquiry_id, action="RESPONDED")
        self.assertEqual(response_audit.after_data["note"], "已通过邮件回复客户，开始澄清需求。")
        self.assertFalse("script" in response_audit.after_data["note"])
        self.assertTrue(responded.data["data"]["allowed_actions"]["confirm_requirements"])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(missing_quote.status_code, 409, missing_quote.data)
        self.assertEqual(quoting.status_code, 200, quoting.data)
        self.assertEqual(quoted.status_code, 200, quoted.data)
        self.assertEqual(followed.status_code, 200, followed.data)
        self.assertEqual(followed_again.status_code, 200, followed_again.data)
        self.assertEqual(CustomerCommunication.objects.filter(inquiry_links__inquiry_id=inquiry_id).count(), 3)
        timeline = self.client.get(base + "timeline/")
        self.assertEqual(timeline.status_code, 200, timeline.data)
        self.assertEqual(
            len([event for event in timeline.data["data"] if event["source_type"] == "CUSTOMER_COMMUNICATION"]),
            3,
        )
        inquiry.refresh_from_db()
        first_response = inquiry.sla_links.get(stage_code="FIRST_RESPONSE").sla_tracking
        requirement = inquiry.sla_links.get(stage_code="REQUIREMENT_CONFIRMATION").sla_tracking
        self.assertEqual(first_response.tracking_data["target_kind"], "RESPONSE")
        self.assertEqual(first_response.status, SlaTrackingStatus.MET)
        self.assertEqual(requirement.tracking_data["target_kind"], "RESOLUTION")
        self.assertEqual(requirement.status, SlaTrackingStatus.MET)
        self.assertEqual(inquiry.status, "QUOTED")

    def test_detail_exposes_linked_quotations_only_with_quote_view_permission(self):
        created = self.create_inquiry()
        inquiry = Inquiry.objects.get(pk=created.data["data"]["id"])
        quotation = Quotation.objects.create(
            customer_account=self.customer,
            transaction_entity=self.entity,
            source_inquiry=inquiry,
            owner_employee=self.employee,
            quotation_number="INQ03_LINKED_QUOTE",
            subject="关联报价",
        )
        version = QuotationVersion.objects.create(
            quotation=quotation,
            version_number=1,
            currency_code="USD",
            transaction_entity_snapshot={"id": str(self.entity.pk)},
            address_snapshot={},
            contact_snapshot={},
        )
        detail_url = f"/api/v1/inquiries/{inquiry.pk}/"
        hidden = self.client.get(detail_url)
        self.assertEqual(hidden.status_code, 200, hidden.data)
        self.assertEqual(hidden.data["data"]["linked_quotations"], [])

        self.user.user_permissions.add(Permission.objects.get(codename="view_quotation"))
        self.user.refresh_from_db()
        for cache_name in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            if hasattr(self.user, cache_name):
                delattr(self.user, cache_name)
        self.client.force_authenticate(user=self.user)
        visible = self.client.get(detail_url)
        self.assertEqual(visible.status_code, 200, visible.data)
        self.assertEqual(visible.data["data"]["linked_quotations"], [{
            "id": str(quotation.pk),
            "quotation_number": "INQ03_LINKED_QUOTE",
            "subject": "关联报价",
            "status": version.status,
            "version_id": str(version.pk),
            "outcome_status": quotation.outcome_status,
            "accepted_version_id": None,
        }])

    def test_mark_lost_requires_reason_and_persists_it(self):
        created = self.create_inquiry()
        inquiry_id = created.data["data"]["id"]
        base = f"/api/v1/inquiries/{inquiry_id}/"
        submitted = self.client.post(base + "submit/", {}, format="json", HTTP_IF_MATCH=created.headers["ETag"])
        missing = self.client.post(base + "mark-lost/", {}, format="json", HTTP_IF_MATCH=submitted.headers["ETag"])
        lost = self.client.post(
            base + "mark-lost/", {"reason": "客户确认采购计划取消。"}, format="json", HTTP_IF_MATCH=submitted.headers["ETag"]
        )

        inquiry = Inquiry.objects.get(pk=inquiry_id)
        self.assertEqual(missing.status_code, 400, missing.data)
        self.assertEqual(lost.status_code, 200, lost.data)
        self.assertEqual(inquiry.status, "LOST")
        self.assertEqual(inquiry.close_reason_code, "LOST")
        self.assertEqual(inquiry.close_reason_detail, "客户确认采购计划取消。")

    def test_submit_without_items_and_invalid_transition_are_rejected(self):
        created = self.create_inquiry(items=[])
        base = f"/api/v1/inquiries/{created.data['data']['id']}/"
        submit = self.client.post(base + "submit/", {}, format="json", HTTP_IF_MATCH=created.headers["ETag"])
        start = self.client.post(base + "start/", {}, format="json", HTTP_IF_MATCH=created.headers["ETag"])

        self.assertEqual(submit.status_code, 409, submit.data)
        self.assertEqual(start.status_code, 409, start.data)

    def test_inq01_create_auto_assigns_current_salesperson_and_transfer_uses_real_etag(self):
        created = self.create_inquiry()
        inquiry_id = created.data["data"]["id"]
        submitted = self.client.post(
            f"/api/v1/inquiries/{inquiry_id}/submit/", {}, format="json", HTTP_IF_MATCH=created.headers["ETag"]
        )

        metrics = self.client.get("/api/v1/inquiries/metrics/")
        assigned = self.client.post(
            f"/api/v1/inquiries/{inquiry_id}/assign/",
            {"owner_employee_id": str(self.employee.pk), "reason": "测试转交"},
            format="json",
            HTTP_IF_MATCH=submitted.headers["ETag"],
        )
        stale = self.client.post(
            f"/api/v1/inquiries/{inquiry_id}/assign/",
            {"owner_employee_id": str(self.employee.pk)},
            format="json",
            HTTP_IF_MATCH=submitted.headers["ETag"],
        )

        self.assertEqual(metrics.status_code, 200, metrics.data)
        self.assertNotIn("unassigned", metrics.data["data"])
        self.assertEqual(metrics.data["data"]["quote_accepted"], 0)
        self.assertEqual(assigned.status_code, 200, assigned.data)
        self.assertEqual(stale.status_code, 412, stale.data)
        self.assertTrue(InquiryAssignmentHistory.objects.filter(inquiry_id=inquiry_id).exists())

    def test_submit_requires_contact_and_exposes_stable_error_code(self):
        created = self.create_inquiry(customer_contact_id=None)
        response = self.client.post(
            f"/api/v1/inquiries/{created.data['data']['id']}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )

        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["error"]["code"], "INQUIRY_CONTACT_REQUIRED")
        self.assertIn("联系人", response.data["error"]["message"])

    def test_historical_inquiry_can_attach_missing_contact_then_submit(self):
        created = self.create_inquiry(customer_contact_id=None)
        inquiry_id = created.data["data"]["id"]
        attached = self.client.post(
            f"/api/v1/inquiries/{inquiry_id}/attach-contact/",
            {"customer_contact_id": str(self.contact.pk)},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        submitted = self.client.post(
            f"/api/v1/inquiries/{inquiry_id}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=attached.headers["ETag"],
        )

        self.assertEqual(attached.status_code, 200, attached.data)
        self.assertEqual(attached.data["data"]["customer_contact_summary"]["id"], str(self.contact.pk))
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertTrue(submitted.data["data"]["allowed_actions"]["respond"])
        self.assertTrue(
            CustomerTimelineEvent.objects.filter(
                source_type="INQUIRY",
                source_id=inquiry_id,
                event_type="INQUIRY_CONTACT_ATTACHED",
            ).exists()
        )

    def test_inq01_mark_invalid_requires_etag_and_writes_reason(self):
        created = self.create_inquiry()
        inquiry_id = created.data["data"]["id"]
        missing = self.client.post(
            f"/api/v1/inquiries/{inquiry_id}/mark-invalid/", {"reason_code": "SPAM"}, format="json"
        )
        marked = self.client.post(
            f"/api/v1/inquiries/{inquiry_id}/mark-invalid/",
            {"reason_code": "SPAM", "reason_detail": "自动化测试"},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        inquiry = Inquiry.objects.get(pk=inquiry_id)

        self.assertEqual(missing.status_code, 428, missing.data)
        self.assertEqual(marked.status_code, 200, marked.data)
        self.assertEqual(inquiry.status, "CANCELLED")
        self.assertEqual(inquiry.close_reason_code, "SPAM")

    def test_file_link_prevents_cross_customer_reuse_and_tasks_are_queryable(self):
        created = self.create_inquiry()
        inquiry = Inquiry.objects.get(pk=created.data["data"]["id"])
        available_file = BusinessFile.objects.create(
            uploaded_by_employee=self.employee,
            original_name="inquiry.pdf",
            storage_key="tests/inquiries/inquiry.pdf",
            content_type="application/pdf",
            size_bytes=100,
            scan_status="CLEAN",
        )
        foreign_file = BusinessFile.objects.create(
            uploaded_by_employee=self.employee,
            original_name="foreign.pdf",
            storage_key="tests/inquiries/foreign.pdf",
            content_type="application/pdf",
            size_bytes=100,
            scan_status="CLEAN",
        )
        CustomerFileLink.objects.create(
            customer_account=self.other_customer,
            business_file=foreign_file,
            file_role="ATTACHMENT",
        )
        linked = self.client.post(
            f"/api/v1/inquiries/{inquiry.pk}/files/",
            {"file_id": str(available_file.pk), "file_role": "ATTACHMENT"},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        rejected = self.client.post(
            f"/api/v1/inquiries/{inquiry.pk}/files/",
            {"file_id": str(foreign_file.pk), "file_role": "ATTACHMENT"},
            format="json",
            HTTP_IF_MATCH=linked.headers["ETag"],
        )
        task = BusinessTask.objects.create(
            assignee_employee=self.employee,
            created_by_employee=self.employee,
            title="处理询价",
        )
        InquiryTaskLink.objects.create(inquiry=inquiry, business_task=task)
        tasks = self.client.get(f"/api/v1/inquiries/{inquiry.pk}/tasks/")

        self.assertEqual(linked.status_code, 201, linked.data)
        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertIn("file_id", rejected.data["error"]["field_errors"])
        self.assertEqual(tasks.status_code, 200, tasks.data)
        self.assertEqual(tasks.data["data"][0]["id"], str(task.pk))

    @patch("apps.files.uploads._clamav_scan", return_value="stream: OK")
    def test_wang_editor_image_upload_insert_save_and_reopen(self, _scan):
        created = self.create_inquiry()
        inquiry_id = created.data["data"]["id"]
        upload = self.client.post(
            f"/api/v1/inquiries/{inquiry_id}/images/",
            {"file": SimpleUploadedFile("conversation.gif", b"GIF89a\x00\x00\x00", content_type="image/gif")},
            format="multipart",
            HTTP_IF_MATCH=created.headers["ETag"],
        )

        self.assertEqual(upload.status_code, 200, upload.data)
        self.assertEqual(upload.data["errno"], 0, upload.data)
        source = upload.data["data"]["url"]
        self.assertEqual(upload.data["data"]["alt"], "conversation.gif")
        self.assertEqual(upload.data["data"]["etag"], upload.headers["ETag"])

        saved = self.client.patch(
            f"/api/v1/inquiries/{inquiry_id}/draft/",
            {"description": f'<p>已上传截图</p><img src="{source}" alt="沟通截图" onerror="alert(1)">', "idempotency_key": "wang-editor-image-save"},
            format="json",
            HTTP_IF_MATCH=upload.headers["ETag"],
        )
        reopened = self.client.get(f"/api/v1/inquiries/{inquiry_id}/")
        preview = self.client.get(source)
        business_file = BusinessFile.objects.get(inquiry_links__inquiry_id=inquiry_id)

        try:
            self.assertEqual(saved.status_code, 200, saved.data)
            self.assertIn(f'<img src="{source}" alt="沟通截图">', saved.data["data"]["description"])
            self.assertNotIn("onerror", saved.data["data"]["description"])
            self.assertEqual(reopened.status_code, 200, reopened.data)
            self.assertIn(source, reopened.data["data"]["description"])
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(preview["Content-Type"], "image/gif")
        finally:
            (Path(settings.MEDIA_ROOT) / business_file.storage_key).unlink(missing_ok=True)

    def test_wang_editor_image_upload_rejects_invalid_format_and_oversized_file(self):
        created = self.create_inquiry()
        inquiry_id = created.data["data"]["id"]
        invalid = self.client.post(
            f"/api/v1/inquiries/{inquiry_id}/images/",
            {"file": SimpleUploadedFile("conversation.txt", b"not an image", content_type="text/plain")},
            format="multipart",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        oversized = self.client.post(
            f"/api/v1/inquiries/{inquiry_id}/images/",
            {"file": SimpleUploadedFile("conversation.gif", b"GIF89a" + b"0" * (5 * 1024 * 1024), content_type="image/gif")},
            format="multipart",
            HTTP_IF_MATCH=created.headers["ETag"],
        )

        self.assertEqual(invalid.status_code, 200, invalid.data)
        self.assertEqual(invalid.data["errno"], 1, invalid.data)
        self.assertIn("JPG、PNG、GIF 或 WebP", invalid.data["message"])
        self.assertEqual(oversized.status_code, 200, oversized.data)
        self.assertEqual(oversized.data["errno"], 1, oversized.data)
        self.assertIn("不超过 5MB", oversized.data["message"])
