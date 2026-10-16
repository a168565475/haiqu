from datetime import timedelta
import json
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.crm.models import CustomerTimelineEvent
from apps.customers.models import (
    CustomerAccount,
    CustomerAssignment,
    CustomerContact,
    CustomerEntityAddress,
    CustomerTransactionEntity,
)
from apps.files.models import BusinessFile
from apps.inquiries.models import Inquiry, InquiryItem, InquiryStatus
from apps.organizations.models import Employee
from apps.quotations.models import (
    Quotation,
    QuotationLine,
    QuotationOutcomeStatus,
    QuotationVersion,
    QuotationVersionStatus,
)
from apps.reference_data.models import ProductCategory, ProductColor, ProductItemType
from apps.workflow.models import BusinessTask, SlaPolicy, SlaTrackingStatus, TaskStatus

from ..models import SampleFeedback, SampleFeeRecord, SampleRequest, SampleRequestStatus, SampleShipmentEvent


@override_settings(FILE_VIRUS_SCAN_ENABLED=True)
class SampleApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="sample_api_user")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="SAMPLE_API_USER",
            display_name="样品接口测试员工",
        )
        self.other_user = user_model.objects.create_user(username="sample_api_other")
        self.other_employee = Employee.objects.create(
            user=self.other_user,
            employee_code="SAMPLE_API_OTHER",
            display_name="其他样品员工",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(
                content_type__app_label__in=["samples", "workflow", "inquiries", "quotations"]
            )
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.customer = self.create_customer("SAMPLE_CUSTOMER", "样品客户", self.employee)
        self.other_customer = self.create_customer(
            "OTHER_SAMPLE_CUSTOMER", "其他样品客户", self.other_employee
        )
        self.entity = CustomerTransactionEntity.objects.create(
            customer_account=self.customer,
            entity_code="SAMPLE_ENTITY",
            legal_name="样品交易主体",
        )
        self.address = CustomerEntityAddress.objects.create(
            transaction_entity=self.entity,
            address_code="SAMPLE_ADDRESS",
            country_code="CN",
            city="深圳",
            address_line1="样品路 1 号",
        )
        self.contact = CustomerContact.objects.create(
            customer_account=self.customer,
            transaction_entity=self.entity,
            display_name="样品联系人",
        )
        self.product_category = ProductCategory.objects.create(
            item_type=ProductItemType.FINISHED,
            category_name="样品接口成品类别",
        )
        self.product_color = ProductColor.objects.create(
            color_card="标准色卡",
            color_code="C-001",
            color_name="海军蓝",
        )
        self.second_product_color = ProductColor.objects.create(
            color_card="标准色卡",
            color_code="C-002",
            color_name="海军蓝",
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

    def payload(self, **overrides):
        data = {
            "customer_account_id": str(self.customer.pk),
            "transaction_entity_id": str(self.entity.pk),
            "customer_contact_id": str(self.contact.pk),
            "owner_employee_id": str(self.employee.pk),
            "purpose": "客户测试",
            "requested_at": timezone.now().isoformat(),
            "items": [
                {
                    "product_description_snapshot": "测试样品",
                    "requested_quantity": "2.0000",
                    "unit_code": "PCS",
                }
            ],
        }
        data.update(overrides)
        return data

    def create_sample(self, **overrides):
        response = self.client.post("/api/v1/sample-requests/", self.payload(**overrides), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def sample_form_payload(self, **overrides):
        today = timezone.localdate().isoformat()
        data = {
            "manual_request_number": "FORM-001",
            "customer_account_id": str(self.customer.pk),
            "customer_contact_id": str(self.contact.pk),
            "owner_employee_id": str(self.employee.pk),
            "shipping_method": "MAIL",
            "order_date": today,
            "sample_due_date": today,
            "delivery_batch": "SINGLE",
            "sample_type": "PRE_SALES",
            "is_repeat_order": False,
            "submitted_on": today,
            "purpose": "特殊交付说明",
            "idempotency_key": "sample-form-create-001",
            "products": [
                {
                    "client_key": "product-one",
                    "category_id": str(self.product_category.pk),
                    "product_name": "休闲椅样品",
                    "specification": "常规规格",
                    "length_cm": "80.00",
                    "armrest_width_cm": None,
                    "seat_width_cm": "52.00",
                    "back_height_cm": "45.00",
                    "seat_height_cm": "48.00",
                    "details": [
                        {
                            "product_color_id": str(self.product_color.pk),
                            "color_code": "CUSTOM-C-001",
                            "sample_quantity": 2,
                            "tolerance": "PLUS_MINUS_0_5_CM",
                            "notes": "首件确认",
                            "cutting_reported_quantity": 0,
                            "metalwork_reported_quantity": 0,
                            "cutting_completed": False,
                            "metalwork_completed": False,
                        },
                        {
                            "product_color_id": str(self.second_product_color.pk),
                            "sample_quantity": 3,
                            "tolerance": "NONE",
                            "notes": "同名不同色号",
                            "cutting_reported_quantity": 0,
                            "metalwork_reported_quantity": 0,
                            "cutting_completed": False,
                            "metalwork_completed": False,
                        },
                    ],
                    "sampling_details": [
                        {
                            "client_key": "sampling-material-pipe",
                            "template_key": "material-pipe",
                            "detail_type": "材料",
                            "category_label": "管材",
                            "is_selected": True,
                            "description": "主管材确认",
                        },
                        {
                            "client_key": "sampling-carton-size",
                            "template_key": "packaging-carton-size",
                            "detail_type": "包材-纸箱",
                            "category_label": "尺寸",
                            "is_selected": False,
                            "description": "",
                        },
                    ],
                }
            ],
        }
        data.update(overrides)
        return data

    def create_sample_form(self, payload=None):
        payload = payload or self.sample_form_payload()
        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root), patch(
            "apps.files.uploads._clamav_scan", return_value="ClamAV test clean"
        ):
            response = self.client.post(
                "/api/v1/sample-requests/",
                {
                    "payload": json.dumps(payload),
                    "task_sheet_product-one": SimpleUploadedFile(
                        "task.png",
                        b"\x89PNG\r\n\x1a\n" + b"task-sheet",
                        content_type="image/png",
                    ),
                    "sampling_image_sampling-material-pipe": SimpleUploadedFile(
                        "pipe.png",
                        b"\x89PNG\r\n\x1a\n" + b"sampling-detail",
                        content_type="image/png",
                    ),
                },
                format="multipart",
            )
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def test_independent_form_options_context_and_direct_pending_create(self):
        inquiry, source_item = self.create_inquiry_with_item(number="INQ-FORM-CONTEXT")
        inquiry.received_at = timezone.now() - timedelta(days=2)
        inquiry.requested_due_at = timezone.now() + timedelta(days=7)
        inquiry.save(update_fields=["received_at", "requested_due_at", "updated_at"])
        InquiryItem.objects.create(
            inquiry=inquiry,
            line_number=2,
            product_description="来源产品二",
            specification="来源规格二",
            quantity=2,
            unit_code="PCS",
        )
        options = self.client.get("/api/v1/sample-requests/form-options/")
        context = self.client.get(
            "/api/v1/sample-requests/form-context/",
            {"sourceType": "inquiry", "sourceId": str(inquiry.pk)},
        )
        created = self.create_sample_form()

        self.assertEqual(options.status_code, 200, options.data)
        self.assertEqual(len(options.data["data"]["sampling_detail_template"]), 19)
        self.assertEqual(options.data["data"]["sampling_detail_template"][0]["category"], "管材")
        self.assertEqual(options.data["data"]["color_cards"].count("标准色卡"), 1)
        self.assertEqual(
            len([row for row in options.data["data"]["colors"] if row["color_card"] == "标准色卡"]),
            2,
        )
        self.assertEqual(context.status_code, 200, context.data)
        self.assertEqual(
            context.data["data"]["basic_info"],
            {
                "order_date": timezone.localtime(inquiry.received_at).date().isoformat(),
                "sample_due_date": timezone.localtime(inquiry.requested_due_at).date().isoformat(),
            },
        )
        self.assertEqual(context.data["data"]["products"][0]["source_inquiry_item_id"], str(source_item.pk))
        self.assertEqual(len(context.data["data"]["products"]), 2)
        _, quotation_version, _ = self.create_quotation_version_with_line(inquiry, source_item)
        quotation_context = self.client.get(
            "/api/v1/sample-requests/form-context/",
            {"sourceType": "quotation", "sourceId": str(quotation_version.pk)},
        )
        self.assertEqual(quotation_context.status_code, 200, quotation_context.data)
        self.assertEqual(quotation_context.data["data"]["basic_info"], context.data["data"]["basic_info"])
        invalid_context = self.client.get(
            "/api/v1/sample-requests/form-context/",
            {"sourceType": "inquiry", "sourceId": "not-a-uuid"},
        )
        self.assertEqual(invalid_context.status_code, 400, invalid_context.data)
        self.assertEqual(created.data["data"]["request_number"], "HTS-FORM-001")
        self.assertEqual(created.data["data"]["status"], SampleRequestStatus.PENDING)
        self.assertEqual(created.data["data"]["created_by"]["id"], str(self.employee.pk))
        self.assertEqual(created.data["data"]["products"][0]["total_sample_quantity"], 5)
        self.assertEqual(created.data["data"]["products"][0]["details"][0]["color_code"], "CUSTOM-C-001")
        self.assertEqual(len(created.data["data"]["products"][0]["sampling_details"]), 2)
        self.assertTrue(created.data["data"]["products"][0]["sampling_details"][0]["is_selected"])
        self.assertEqual(
            created.data["data"]["products"][0]["sampling_details"][0]["image_file_name"],
            "pipe.png",
        )
        self.assertEqual(len(created.data["data"]["items"]), 2)
        self.assertEqual(created.data["data"]["items"][0]["unit_code"], "PCS")
        self.assertEqual(created.data["data"]["items"][0]["color_code_snapshot"], "CUSTOM-C-001")

    def test_new_production_workflow_finance_pmc_parameters_and_finish(self):
        created = self.create_sample_form(
            self.sample_form_payload(
                manual_request_number="FLOW-001",
                idempotency_key="sample-production-flow-001",
            )
        )
        sample_id = created.data["data"]["id"]
        self.assertEqual(
            [record["stage"] for record in created.data["data"]["workflow_records"]],
            ["REQUEST_CREATED", "REQUIREMENTS_COMPLETED"],
        )

        missing_finance = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/finance-confirm/",
            {},
            format="multipart",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        self.assertEqual(missing_finance.status_code, 400, missing_finance.data)

        finance = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/finance-confirm/",
            {"note": "财务人工核对通过"},
            format="multipart",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        self.assertEqual(finance.status_code, 200, finance.data)
        self.assertEqual(finance.data["data"]["status"], SampleRequestStatus.PMC_REVIEW)
        self.assertEqual(
            finance.data["data"]["workflow_records"][-1]["stage"],
            "FINANCE_CONFIRMED",
        )

        stale_pmc = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/pmc-approve/",
            {"note": ""},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        self.assertEqual(stale_pmc.status_code, 412, stale_pmc.data)
        pmc = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/pmc-approve/",
            {"note": ""},
            format="json",
            HTTP_IF_MATCH=finance.headers["ETag"],
        )
        self.assertEqual(pmc.status_code, 200, pmc.data)
        self.assertEqual(pmc.data["data"]["status"], SampleRequestStatus.METALWORK_PENDING)

        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root), patch(
            "apps.samples.uploads._clamav_scan", return_value="ClamAV test clean"
        ):
            metalwork = self.client.post(
                f"/api/v1/sample-requests/{sample_id}/metalwork-parameters/",
                {
                    "note": "金工参数确认",
                    "file": SimpleUploadedFile(
                        "metalwork.png",
                        b"\x89PNG\r\n\x1a\n",
                        content_type="image/png",
                    ),
                },
                format="multipart",
                HTTP_IF_MATCH=pmc.headers["ETag"],
            )
            self.assertEqual(metalwork.status_code, 200, metalwork.data)
            self.assertEqual(metalwork.data["data"]["status"], SampleRequestStatus.CUTTING_PENDING)

            second_metalwork = self.client.post(
                f"/api/v1/sample-requests/{sample_id}/metalwork-parameters/",
                {
                    "file": SimpleUploadedFile(
                        "metalwork-2.png",
                        b"\x89PNG\r\n\x1a\nsecond",
                        content_type="image/png",
                    ),
                },
                format="multipart",
                HTTP_IF_MATCH=metalwork.headers["ETag"],
            )
            self.assertEqual(second_metalwork.status_code, 200, second_metalwork.data)

            cutting = self.client.post(
                f"/api/v1/sample-requests/{sample_id}/cutting-parameters/",
                {
                    "note": "裁剪参数确认",
                    "file": SimpleUploadedFile(
                        "cutting.png",
                        b"\x89PNG\r\n\x1a\ncutting",
                        content_type="image/png",
                    ),
                },
                format="multipart",
                HTTP_IF_MATCH=second_metalwork.headers["ETag"],
            )
            self.assertEqual(cutting.status_code, 200, cutting.data)
            self.assertEqual(cutting.data["data"]["status"], SampleRequestStatus.FINISHED)
            self.assertEqual(
                [record["stage"] for record in cutting.data["data"]["workflow_records"]],
                [
                    "REQUEST_CREATED",
                    "REQUIREMENTS_COMPLETED",
                    "FINANCE_CONFIRMED",
                    "PMC_APPROVED",
                    "METALWORK_PARAMETERS",
                    "CUTTING_PARAMETERS",
                    "WORKFLOW_FINISHED",
                ],
            )
            metalwork_image = next(
                image for image in cutting.data["data"]["parameter_images"]
                if image["parameter_type"] == "METALWORK"
            )
            downloaded = self.client.get(
                f"/api/v1/sample-requests/{sample_id}/business-files/{metalwork_image['file_id']}/"
            )
            self.assertEqual(downloaded.status_code, 200)

    def test_form_idempotency_duplicate_number_and_edit_stage_lock(self):
        created = self.create_sample_form()
        sample_id = created.data["data"]["id"]
        detail = created.data["data"]
        replayed = self.client.post(
            "/api/v1/sample-requests/",
            {"payload": json.dumps(self.sample_form_payload())},
            format="multipart",
        )
        self.assertEqual(replayed.status_code, 200, replayed.data)
        self.assertEqual(replayed.headers["Idempotent-Replayed"], "true")
        self.assertEqual(replayed.data["data"]["id"], sample_id)
        duplicate_payload = self.sample_form_payload(idempotency_key="sample-form-create-duplicate")
        duplicate = self.client.post(
            "/api/v1/sample-requests/",
            {"payload": json.dumps(duplicate_payload)},
            format="multipart",
        )
        self.assertEqual(duplicate.status_code, 400, duplicate.data)

        edit_payload = self.sample_form_payload(idempotency_key="")
        product = detail["products"][0]
        edit_payload["products"][0].update(
            {
                "id": product["id"],
                "client_key": product["id"],
                "product_name": "休闲椅样品（已编辑）",
            }
        )
        for submitted, saved in zip(edit_payload["products"][0]["details"], product["details"], strict=True):
            submitted["id"] = saved["id"]
        for submitted, saved in zip(
            edit_payload["products"][0]["sampling_details"],
            product["sampling_details"],
            strict=True,
        ):
            submitted["id"] = saved["id"]
            submitted["client_key"] = saved["id"]
        edit_payload["products"][0]["sampling_details"][0]["detail_type"] = "材料（已编辑）"
        edit_payload["products"][0]["sampling_details"][0]["is_selected"] = False
        edit_payload["products"][0]["sampling_details"].append(
            {
                "client_key": "sampling-appended-row",
                "template_key": "",
                "detail_type": "新增打样项",
                "category_label": "自定义",
                "is_selected": True,
                "description": "追加测试",
            }
        )
        edit_payload["products"][0]["details"][0]["color_code"] = "EDIT-C-001"
        edit_payload["products"][0]["details"].reverse()
        updated = self.client.patch(
            f"/api/v1/sample-requests/{sample_id}/form/",
            {"payload": json.dumps(edit_payload)},
            format="multipart",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["data"]["products"][0]["product_name"], "休闲椅样品（已编辑）")
        self.assertEqual(len(updated.data["data"]["products"][0]["sampling_details"]), 3)
        self.assertEqual(
            updated.data["data"]["products"][0]["sampling_details"][0]["detail_type"],
            "材料（已编辑）",
        )
        self.assertFalse(updated.data["data"]["products"][0]["sampling_details"][0]["is_selected"])
        self.assertEqual(updated.data["data"]["products"][0]["details"][0]["id"], product["details"][1]["id"])
        updated_details = {row["id"]: row for row in updated.data["data"]["products"][0]["details"]}
        self.assertEqual(updated_details[product["details"][0]["id"]]["color_code"], "EDIT-C-001")
        stale = self.client.patch(
            f"/api/v1/sample-requests/{sample_id}/form/",
            {"payload": json.dumps(edit_payload)},
            format="multipart",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        self.assertEqual(stale.status_code, 412, stale.data)

        for submitted, saved in zip(
            edit_payload["products"][0]["sampling_details"],
            updated.data["data"]["products"][0]["sampling_details"],
            strict=True,
        ):
            submitted["id"] = saved["id"]
            submitted["client_key"] = saved["id"]

        SampleFeeRecord.objects.create(sample_request_id=sample_id, currency_code="USD")
        locked = self.client.get(f"/api/v1/sample-requests/{sample_id}/")
        self.assertEqual(locked.data["data"]["edit_capabilities"]["mode"], "REPORT_ONLY")
        locked_payload = edit_payload
        locked_payload["products"][0]["product_name"] = "不允许修改"
        rejected = self.client.patch(
            f"/api/v1/sample-requests/{sample_id}/form/",
            {"payload": json.dumps(locked_payload)},
            format="multipart",
            HTTP_IF_MATCH=locked.headers["ETag"],
        )
        self.assertEqual(rejected.status_code, 409, rejected.data)

        locked_payload["products"][0]["product_name"] = "休闲椅样品（已编辑）"
        locked_payload["products"][0]["details"][0]["cutting_reported_quantity"] = 1
        locked_payload["products"][0]["details"][0]["cutting_completed"] = True
        locked_payload["purpose"] = "后续阶段特殊说明"
        reported = self.client.patch(
            f"/api/v1/sample-requests/{sample_id}/form/",
            {"payload": json.dumps(locked_payload)},
            format="multipart",
            HTTP_IF_MATCH=locked.headers["ETag"],
        )
        self.assertEqual(reported.status_code, 200, reported.data)
        self.assertEqual(reported.data["data"]["items"][0]["cutting_reported_quantity"], 1)
        self.assertTrue(reported.data["data"]["items"][0]["cutting_completed"])

        SampleRequest.objects.filter(pk=sample_id).update(status=SampleRequestStatus.CONFIRMED)
        terminal = self.client.get(f"/api/v1/sample-requests/{sample_id}/")
        self.assertEqual(terminal.data["data"]["edit_capabilities"]["mode"], "READ_ONLY")
        terminal_update = self.client.patch(
            f"/api/v1/sample-requests/{sample_id}/form/",
            {"payload": json.dumps(locked_payload)},
            format="multipart",
            HTTP_IF_MATCH=terminal.headers["ETag"],
        )
        self.assertEqual(terminal_update.status_code, 409, terminal_update.data)

    def test_form_requires_task_sheet_and_rejects_forged_image(self):
        original_file_count = BusinessFile.objects.count()
        payload = self.sample_form_payload(
            manual_request_number="FORM-FILE-001",
            idempotency_key="sample-form-file-missing",
        )
        missing = self.client.post(
            "/api/v1/sample-requests/",
            {"payload": json.dumps(payload)},
            format="multipart",
        )
        self.assertEqual(missing.status_code, 400, missing.data)
        self.assertFalse(SampleRequest.objects.filter(request_number="HTS-FORM-FILE-001").exists())

        payload["manual_request_number"] = "FORM-FILE-002"
        payload["idempotency_key"] = "sample-form-file-forged"
        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            forged = self.client.post(
                "/api/v1/sample-requests/",
                {
                    "payload": json.dumps(payload),
                    "task_sheet_product-one": SimpleUploadedFile(
                        "forged.png",
                        b"this-is-not-a-png",
                        content_type="image/png",
                    ),
                },
                format="multipart",
            )
        self.assertEqual(forged.status_code, 400, forged.data)
        self.assertFalse(SampleRequest.objects.filter(request_number="HTS-FORM-FILE-002").exists())
        self.assertEqual(BusinessFile.objects.count(), original_file_count)

    def test_independent_form_creates_from_inquiry_and_quotation_sources(self):
        inquiry, inquiry_item = self.create_inquiry_with_item(number="INQ-FORM-SOURCE")
        inquiry_payload = self.sample_form_payload(
            manual_request_number="FORM-INQUIRY",
            idempotency_key="sample-form-inquiry-source",
            source_type="inquiry",
            source_id=str(inquiry.pk),
        )
        inquiry_payload["products"][0]["source_inquiry_item_id"] = str(inquiry_item.pk)
        inquiry_created = self.create_sample_form(inquiry_payload)
        self.assertEqual(str(inquiry_created.data["data"]["source_inquiry"]), str(inquiry.pk))
        self.assertEqual(
            str(inquiry_created.data["data"]["products"][0]["source_inquiry_item_id"]),
            str(inquiry_item.pk),
        )

        quotation, version, line = self.create_quotation_version_with_line(inquiry, inquiry_item)
        context = self.client.get(
            "/api/v1/sample-requests/form-context/",
            {"sourceType": "quotation", "sourceId": str(version.pk)},
        )
        self.assertEqual(context.status_code, 200, context.data)
        self.assertEqual(context.data["data"]["source_version_id"], str(version.pk))
        self.assertEqual(context.data["data"]["products"][0]["source_quotation_line_id"], str(line.pk))

        quotation_payload = self.sample_form_payload(
            manual_request_number="FORM-QUOTATION",
            idempotency_key="sample-form-quotation-source",
            source_type="quotation",
            source_id=str(version.pk),
        )
        quotation_payload["products"][0].update(
            {
                "source_inquiry_item_id": str(inquiry_item.pk),
                "source_quotation_line_id": str(line.pk),
            }
        )
        quotation_created = self.create_sample_form(quotation_payload)
        self.assertEqual(str(quotation_created.data["data"]["source_quotation_version"]), str(version.pk))
        self.assertEqual(
            str(quotation_created.data["data"]["products"][0]["source_quotation_line_id"]),
            str(line.pk),
        )

        saved_product = quotation_created.data["data"]["products"][0]
        quotation_payload["idempotency_key"] = ""
        quotation_payload["owner_employee_id"] = str(self.other_employee.pk)
        quotation_payload["products"][0].update(
            {"id": saved_product["id"], "client_key": saved_product["id"]}
        )
        for submitted, saved in zip(
            quotation_payload["products"][0]["details"],
            saved_product["details"],
            strict=True,
        ):
            submitted["id"] = saved["id"]
        owner_tampering = self.client.patch(
            f"/api/v1/sample-requests/{quotation_created.data['data']['id']}/form/",
            {"payload": json.dumps(quotation_payload)},
            format="multipart",
            HTTP_IF_MATCH=quotation_created.headers["ETag"],
        )
        self.assertEqual(owner_tampering.status_code, 400, owner_tampering.data)

    def create_inquiry_with_item(self, *, number="INQ-SAMPLE-SOURCE", customer=None, owner=None):
        customer = customer or self.customer
        owner = owner or self.employee
        inquiry = Inquiry.objects.create(
            customer_account=customer,
            transaction_entity=self.entity if customer == self.customer else None,
            customer_contact=self.contact if customer == self.customer else None,
            owner_employee=owner,
            inquiry_number=number,
            subject="样品来源询盘",
            received_at=timezone.now(),
        )
        item = InquiryItem.objects.create(
            inquiry=inquiry,
            line_number=1,
            product_description="折叠露营床",
            specification="600D 牛津布 / 黑色",
            quantity="1200.0000",
            unit_code="PCS",
        )
        inquiry.status = InquiryStatus.NEW
        inquiry.save(update_fields=["status", "updated_at"])
        return inquiry, item

    def create_quotation_version_with_line(
        self, inquiry, inquiry_item, product_image=None, other_product_image=None,
    ):
        quotation = Quotation.objects.create(
            customer_account=inquiry.customer_account,
            transaction_entity=self.entity,
            source_inquiry=inquiry,
            owner_employee=self.employee,
            quotation_number="QUO-SAMPLE-SOURCE",
            subject="样品来源报价",
        )
        version = QuotationVersion.objects.create(
            quotation=quotation,
            version_number=1,
            currency_code="USD",
            transaction_entity_snapshot={"legal_name": self.entity.legal_name},
            address_snapshot={"address_line1": self.address.address_line1},
            contact_snapshot={"id": str(self.contact.pk), "display_name": self.contact.display_name},
        )
        line = QuotationLine.objects.create(
            quotation_version=version,
            source_inquiry_item=inquiry_item,
            line_number=1,
            product_description_snapshot="折叠露营床",
            specification_snapshot="600D 牛津布 / 黑色",
            quantity="1200.0000",
            unit_code="PCS",
            unit_price="18.5000",
            line_total="22200.0000",
            product_image=product_image,
        )
        if other_product_image is not None:
            QuotationLine.objects.create(
                quotation_version=version,
                line_number=2,
                product_description_snapshot="其他报价产品",
                specification_snapshot="其他规格",
                quantity="1.0000",
                unit_code="PCS",
                unit_price="10.0000",
                line_total="10.0000",
                product_image=other_product_image,
            )
        now = timezone.now()
        version.status = QuotationVersionStatus.SENT
        version.locked_at = now
        version.issued_at = now
        version.save(update_fields=["status", "locked_at", "issued_at", "updated_at"])
        return quotation, version, line

    def test_create_from_inquiry_inherits_source_and_is_idempotent(self):
        inquiry, inquiry_item = self.create_inquiry_with_item()
        payload = {
            "inquiry_id": str(inquiry.pk),
            "sample_type": "PRE_SALES",
            "purpose": "客户要求寄样",
            "idempotency_key": "sample-from-inquiry-001",
            "items": [{"source_item_id": str(inquiry_item.pk), "requested_quantity": 1}],
        }
        created = self.client.post("/api/v1/sample-requests/create-from-inquiry/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.headers["Idempotent-Replayed"], "false")
        data = created.data["data"]
        self.assertEqual(str(data["customer_account"]), str(self.customer.pk))
        self.assertEqual(str(data["customer_contact"]), str(self.contact.pk))
        self.assertEqual(str(data["source_inquiry"]), str(inquiry.pk))
        self.assertIsNone(data["source_quotation_version"])
        self.assertEqual(data["status"], SampleRequestStatus.PENDING_COMPLETION)
        self.assertTrue(data["request_number"].startswith("SRQ-"))
        self.assertEqual(data["intake_number"], data["request_number"])
        self.assertEqual(data["requested_by"]["id"], str(self.employee.pk))
        self.assertIsNone(data["created_by"])
        self.assertEqual(data["sla"], [])
        self.assertEqual(len(data["products"]), 1)
        self.assertEqual(str(data["items"][0]["source_inquiry_item"]), str(inquiry_item.pk))
        self.assertEqual(data["items"][0]["product_description_snapshot"], "折叠露营床")
        replayed = self.client.post("/api/v1/sample-requests/create-from-inquiry/", payload, format="json")
        self.assertEqual(replayed.status_code, 200, replayed.data)
        self.assertEqual(replayed.headers["Idempotent-Replayed"], "true")
        self.assertEqual(replayed.data["data"]["id"], data["id"])

    def test_factory_completes_intake_and_starts_sample_sla(self):
        SlaPolicy.objects.create(
            policy_code="SAMPLE_COMPLETION_STANDARD",
            display_name="样品完善后 SLA",
            target_type="SAMPLE_REQUEST",
            resolution_minutes=120,
            is_enabled=True,
        )
        inquiry, inquiry_item = self.create_inquiry_with_item(number="INQ-COMPLETE-SAMPLE")
        created = self.client.post(
            "/api/v1/sample-requests/create-from-inquiry/",
            {
                "inquiry_id": str(inquiry.pk),
                "sample_type": "PRE_SALES",
                "sample_due_date": timezone.localdate().isoformat(),
                "purpose": "业务员提交的说明",
                "idempotency_key": "sample-completion-001",
                "items": [{"source_item_id": str(inquiry_item.pk), "requested_quantity": 2}],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        intake = created.data["data"]
        product = intake["products"][0]
        detail = product["details"][0]
        payload = self.sample_form_payload(
            manual_request_number="FACTORY-001",
            idempotency_key="",
            purpose="工厂完善后的特殊说明",
        )
        # 完善页原型没有打样信息明细，不要求生成默认材料行才能提交。
        payload["products"][0]["sampling_details"] = []
        payload["products"][0].update(
            {
                "id": product["id"],
                "client_key": "completion-product",
                "source_inquiry_item_id": str(inquiry_item.pk),
                "source_quotation_line_id": None,
                "product_name": "工厂调整后的产品名称",
            }
        )
        payload["products"][0]["details"] = [
            {
                "id": detail["id"],
                "product_color_id": str(self.product_color.pk),
                "sample_quantity": 2,
                "tolerance": "NONE",
                "notes": "工厂已补齐",
                "cutting_reported_quantity": 0,
                "metalwork_reported_quantity": 0,
                "cutting_completed": False,
                "metalwork_completed": False,
            }
        ]
        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root), patch(
            "apps.files.uploads._clamav_scan", return_value="ClamAV test clean"
        ):
            completed = self.client.patch(
                f"/api/v1/sample-requests/{intake['id']}/form/",
                {
                    "payload": json.dumps(payload),
                    "task_sheet_completion-product": SimpleUploadedFile(
                        "task.png",
                        b"\x89PNG\r\n\x1a\n" + b"task-sheet",
                        content_type="image/png",
                    ),
                },
                format="multipart",
                HTTP_IF_MATCH=created.headers["ETag"],
            )
        self.assertEqual(completed.status_code, 200, completed.data)
        data = completed.data["data"]
        self.assertEqual(data["intake_number"], intake["intake_number"])
        self.assertEqual(data["request_number"], "HTS-FACTORY-001")
        self.assertEqual(data["status"], SampleRequestStatus.PENDING)
        self.assertEqual(data["requested_by"]["id"], str(self.employee.pk))
        self.assertEqual(data["created_by"]["id"], str(self.employee.pk))
        self.assertEqual(data["products"][0]["product_name"], "工厂调整后的产品名称")
        self.assertEqual(data["products"][0]["sampling_details"], [])
        self.assertEqual(len(data["sla"]), 1)
        self.assertEqual(data["sla"][0]["status"], SlaTrackingStatus.RUNNING)
        self.assertTrue(
            AuditLog.objects.filter(
                object_id=intake["id"],
                action="REQUIREMENTS_COMPLETED",
            ).exists()
        )

    def test_requester_can_cancel_own_pending_completion_without_change_permission(self):
        inquiry, inquiry_item = self.create_inquiry_with_item(number="INQ-CANCEL-OWN-SAMPLE")
        created = self.client.post(
            "/api/v1/sample-requests/create-from-inquiry/",
            {
                "inquiry_id": str(inquiry.pk),
                "sample_type": "PRE_SALES",
                "idempotency_key": "sample-cancel-own-001",
                "items": [{"source_item_id": str(inquiry_item.pk), "requested_quantity": 1}],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.user.user_permissions.remove(
            Permission.objects.get(content_type__app_label="samples", codename="change_samplerequest"),
            Permission.objects.get(content_type__app_label="samples", codename="view_all_samplerequest"),
        )
        for cache_name in ("_perm_cache", "_user_perm_cache"):
            if hasattr(self.user, cache_name):
                delattr(self.user, cache_name)

        cancelled = self.client.post(
            f"/api/v1/sample-requests/{created.data['data']['id']}/cancel/",
            {"reason": "客户暂时取消本轮打样"},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(cancelled.data["data"]["status"], SampleRequestStatus.CANCELLED)

    def test_pending_completion_requires_factory_completion_permission(self):
        inquiry, inquiry_item = self.create_inquiry_with_item(number="INQ-COMPLETE-PERMISSION")
        created = self.client.post(
            "/api/v1/sample-requests/create-from-inquiry/",
            {
                "inquiry_id": str(inquiry.pk),
                "sample_type": "PRE_SALES",
                "idempotency_key": "sample-complete-permission-001",
                "items": [{"source_item_id": str(inquiry_item.pk), "requested_quantity": 1}],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.user.user_permissions.remove(
            Permission.objects.get(
                content_type__app_label="samples",
                codename="complete_sample_requirements",
            )
        )
        for cache_name in ("_perm_cache", "_user_perm_cache"):
            if hasattr(self.user, cache_name):
                delattr(self.user, cache_name)

        rejected = self.client.patch(
            f"/api/v1/sample-requests/{created.data['data']['id']}/form/",
            {"payload": "{}"},
            format="multipart",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        self.assertEqual(rejected.status_code, 403, rejected.data)

    def test_create_from_quotation_links_matching_inquiry_and_lineage(self):
        inquiry, inquiry_item = self.create_inquiry_with_item(number="INQ-SAMPLE-QUOTE")
        _, version, line = self.create_quotation_version_with_line(inquiry, inquiry_item)
        response = self.client.post(
            "/api/v1/sample-requests/create-from-quotation/",
            {
                "quotation_version_id": str(version.pk),
                "sample_type": "PRE_SALES",
                "idempotency_key": "sample-from-quotation-001",
                "items": [{"source_line_id": str(line.pk), "requested_quantity": 2}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        data = response.data["data"]
        self.assertEqual(str(data["source_inquiry"]), str(inquiry.pk))
        self.assertEqual(str(data["source_quotation_version"]), str(version.pk))
        self.assertEqual(str(data["customer_contact"]), str(self.contact.pk))
        self.assertEqual(str(data["items"][0]["source_inquiry_item"]), str(inquiry_item.pk))
        self.assertEqual(str(data["items"][0]["source_quotation_line"]), str(line.pk))
        self.assertEqual(data["status"], SampleRequestStatus.PENDING_COMPLETION)

    def create_feedback_pending_sample_from_quotation(self, *, quote_outcome=QuotationOutcomeStatus.OPEN):
        inquiry, inquiry_item = self.create_inquiry_with_item(
            number=f"INQ-REQUOTATION-{Quotation.objects.count() + 1}"
        )
        quotation, version, line = self.create_quotation_version_with_line(inquiry, inquiry_item)
        quotation.outcome_status = quote_outcome
        quotation.save(update_fields=["outcome_status", "updated_at"])
        created = self.client.post(
            "/api/v1/sample-requests/create-from-quotation/",
            {
                "quotation_version_id": str(version.pk),
                "sample_type": "PRE_SALES",
                "idempotency_key": f"sample-requotation-{quotation.pk}",
                "items": [{"source_line_id": str(line.pk), "requested_quantity": 1}],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        sample_request = SampleRequest.objects.get(pk=created.data["data"]["id"])
        sample_request.status = SampleRequestStatus.FEEDBACK_PENDING
        sample_request.save(update_fields=["status", "updated_at"])
        detail = self.client.get(f"/api/v1/sample-requests/{sample_request.pk}/")
        feedback = self.client.post(
            f"/api/v1/sample-requests/{sample_request.pk}/feedback/",
            {
                "feedback_type": "NEGATIVE",
                "feedback_content": "客户要求把椅背高度增加 3 厘米",
                "occurred_at": timezone.now().isoformat(),
                "confirmation_result": "REJECTED",
                "confirmation_source": "CUSTOMER",
                "source_object_version": 1,
                "rejection_reason": "尺寸不符合测试要求",
                "corrective_action_request": "椅背高度增加 3 厘米后重新报价",
            },
            format="json",
            HTTP_IF_MATCH=detail.headers["ETag"],
        )
        self.assertEqual(feedback.status_code, 201, feedback.data)
        return quotation, version, line, sample_request, feedback

    def test_feedback_can_copy_same_customer_history_into_next_quote_version(self):
        quotation, version, line, sample_request, feedback = self.create_feedback_pending_sample_from_quotation()
        feedback_id = feedback.data["data"]["id"]
        options = self.client.get(
            f"/api/v1/sample-requests/{sample_request.pk}/feedback/{feedback_id}/requotation-options/"
        )
        self.assertEqual(options.status_code, 200, options.data)
        selected = next(item for item in options.data["data"] if item["version_id"] == str(version.pk))
        self.assertEqual(selected["target_mode"], "APPEND_VERSION")
        self.assertIn("V2", selected["target_label"])

        payload = {
            "source_quotation_version_id": str(version.pk),
            "valid_until": (timezone.localdate() + timedelta(days=30)).isoformat(),
            "notes": "按客户尺寸反馈调整",
        }
        created = self.client.post(
            f"/api/v1/sample-requests/{sample_request.pk}/feedback/{feedback_id}/create-requotation/",
            payload,
            format="json",
            HTTP_IF_MATCH=feedback.headers["ETag"],
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["data"]["quotation_id"], str(quotation.pk))
        self.assertEqual(created.data["data"]["version_number"], 2)
        copied_version = QuotationVersion.objects.get(pk=created.data["data"]["quotation_version_id"])
        copied_line = copied_version.lines.get()
        self.assertEqual(copied_version.parent_version_id, version.pk)
        self.assertEqual(copied_line.source_inquiry_item_id, line.source_inquiry_item_id)
        self.assertEqual(copied_line.product_description_snapshot, line.product_description_snapshot)
        recorded_feedback = SampleFeedback.objects.get(pk=feedback_id)
        self.assertEqual(recorded_feedback.requotation_source_version_id, version.pk)
        self.assertEqual(recorded_feedback.resulting_quotation_version_id, copied_version.pk)

        replayed = self.client.post(
            f"/api/v1/sample-requests/{sample_request.pk}/feedback/{feedback_id}/create-requotation/",
            payload,
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        self.assertEqual(replayed.status_code, 200, replayed.data)
        self.assertTrue(replayed.data["data"]["replayed"])
        self.assertEqual(quotation.versions.count(), 2)

    def test_feedback_can_copy_another_same_customer_quote_into_original_open_quote(self):
        quotation, _, _, sample_request, feedback = self.create_feedback_pending_sample_from_quotation()
        history_quote = Quotation.objects.create(
            customer_account=self.customer,
            transaction_entity=self.entity,
            owner_employee=self.employee,
            quotation_number="QUO-SAME-CUSTOMER-HISTORY",
            subject="同客户历史扶手椅报价",
        )
        history_version = QuotationVersion.objects.create(
            quotation=history_quote,
            version_number=3,
            currency_code="EUR",
            contact_snapshot={"display_name": "历史联系人"},
        )
        QuotationLine.objects.create(
            quotation_version=history_version,
            line_number=1,
            product_description_snapshot="历史扶手椅",
            specification_snapshot="加高椅背",
            quantity="800.0000",
            unit_code="PCS",
            unit_price="26.5000",
            line_total="21200.0000",
        )
        feedback_id = feedback.data["data"]["id"]
        created = self.client.post(
            f"/api/v1/sample-requests/{sample_request.pk}/feedback/{feedback_id}/create-requotation/",
            {
                "source_quotation_version_id": str(history_version.pk),
                "valid_until": (timezone.localdate() + timedelta(days=30)).isoformat(),
            },
            format="json",
            HTTP_IF_MATCH=feedback.headers["ETag"],
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["data"]["quotation_id"], str(quotation.pk))
        copied = QuotationVersion.objects.get(pk=created.data["data"]["quotation_version_id"])
        self.assertEqual(copied.parent_version_id, history_version.pk)
        self.assertEqual(copied.currency_code, "EUR")
        self.assertEqual(copied.contact_snapshot, {"display_name": "历史联系人"})
        self.assertEqual(copied.lines.get().product_description_snapshot, "历史扶手椅")

    def test_feedback_on_terminal_quote_creates_new_quote_without_reopening_history(self):
        quotation, version, _, sample_request, feedback = self.create_feedback_pending_sample_from_quotation(
            quote_outcome=QuotationOutcomeStatus.CANCELLED
        )
        feedback_id = feedback.data["data"]["id"]
        created = self.client.post(
            f"/api/v1/sample-requests/{sample_request.pk}/feedback/{feedback_id}/create-requotation/",
            {
                "source_quotation_version_id": str(version.pk),
                "valid_until": (timezone.localdate() + timedelta(days=30)).isoformat(),
            },
            format="json",
            HTTP_IF_MATCH=feedback.headers["ETag"],
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertTrue(created.data["data"]["created_new_quotation"])
        self.assertNotEqual(created.data["data"]["quotation_id"], str(quotation.pk))
        quotation.refresh_from_db()
        self.assertEqual(quotation.outcome_status, QuotationOutcomeStatus.CANCELLED)
        self.assertEqual(quotation.versions.count(), 1)

    def test_source_creation_rejects_cross_source_items_and_allows_preproduction_submit(self):
        inquiry, _ = self.create_inquiry_with_item(number="INQ-SAMPLE-MAIN")
        _, other_item = self.create_inquiry_with_item(number="INQ-SAMPLE-OTHER")
        cross = self.client.post(
            "/api/v1/sample-requests/create-from-inquiry/",
            {
                "inquiry_id": str(inquiry.pk),
                "sample_type": "PRE_SALES",
                "idempotency_key": "sample-cross-source-001",
                "items": [{"source_item_id": str(other_item.pk), "requested_quantity": 1}],
            },
            format="json",
        )
        self.assertEqual(cross.status_code, 400, cross.data)
        self.assertIn("items", cross.data["error"]["field_errors"])
        draft = self.create_sample(sample_type="PRE_PRODUCTION")
        submitted = self.client.post(
            f"/api/v1/sample-requests/{draft.data['data']['id']}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=draft.headers["ETag"],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(SampleRequest.objects.get(pk=draft.data["data"]["id"]).status, SampleRequestStatus.PENDING)

    def advance_to_preparing(self, created):
        sample_id = created.data["data"]["id"]
        submitted = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        started = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/start-preparing/",
            {},
            format="json",
            HTTP_IF_MATCH=submitted.headers["ETag"],
        )
        self.assertEqual(started.status_code, 200, started.data)
        return started

    def create_shipment(self, prepared):
        sample_id = prepared.data["data"]["id"]
        item_id = prepared.data["data"]["items"][0]["id"]
        response = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/shipments/",
            {"items": [{"sample_item_id": item_id, "shipped_quantity": "1.0000"}]},
            format="json",
            HTTP_IF_MATCH=prepared.headers["ETag"],
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def test_create_nested_items_generates_number_audit_and_timeline(self):
        response = self.create_sample()
        sample_request = SampleRequest.objects.get(pk=response.data["data"]["id"])

        self.assertRegex(sample_request.request_number, r"^SMP-\d{6}-\d{6,}$")
        self.assertEqual(sample_request.items.get().line_number, 1)
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="SAMPLE_REQUEST", object_id=sample_request.pk, action="CREATED"
            ).exists()
        )
        self.assertTrue(
            CustomerTimelineEvent.objects.filter(
                customer_account=self.customer,
                source_id=sample_request.pk,
                event_type="SAMPLE_CREATED",
            ).exists()
        )

    def test_list_contract_options_summary_and_batch_actions(self):
        created = self.create_sample(sample_type="TESTING")
        sample_id = created.data["data"]["id"]
        self.create_sample(sample_type="TESTING")

        listed = self.client.get("/api/v1/sample-requests/?sample_type=TESTING")
        self.assertEqual(listed.status_code, 200, listed.data)
        self.assertEqual(len(listed.data["data"]), 2)
        row = next(item for item in listed.data["data"] if item["id"] == sample_id)
        self.assertEqual(row["sample_type"], "TESTING")
        self.assertEqual(row["sample_type_display"], "检测样")
        self.assertEqual(row["item_summary"]["count"], 1)
        self.assertTrue(row["etag"])

        summary = self.client.get("/api/v1/sample-requests/summary/")
        options = self.client.get("/api/v1/sample-requests/options/")
        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertEqual(summary.data["data"]["all"], 2)
        self.assertEqual(options.status_code, 200, options.data)
        self.assertIn("TESTING", {item["value"] for item in options.data["data"]["sample_types"]})

        transferred = self.client.post(
            "/api/v1/sample-requests/bulk-transfer/",
            {
                "sample_ids": [sample_id],
                "etags": {sample_id: row["etag"]},
                "owner_employee_id": str(self.other_employee.pk),
                "note": "测试批量转交",
            },
            format="json",
        )
        self.assertEqual(transferred.status_code, 200, transferred.data)
        self.assertEqual(transferred.data["data"]["updated_count"], 1)

        refreshed = self.client.get(f"/api/v1/sample-requests/{sample_id}/")
        reminded = self.client.post(
            "/api/v1/sample-requests/bulk-remind/",
            {
                "sample_ids": [sample_id],
                "etags": {sample_id: refreshed.headers["ETag"]},
                "note": "测试批量提醒",
            },
            format="json",
        )
        self.assertEqual(reminded.status_code, 200, reminded.data)
        self.assertEqual(reminded.data["data"]["task_count"], 1)
        self.assertTrue(SampleRequest.objects.get(pk=sample_id).task_links.exists())

    def test_list_products_expose_color_summary_separately(self):
        created = self.create_sample_form(
            self.sample_form_payload(
                manual_request_number="FORM-LIST-COLOR",
                idempotency_key="sample-form-list-color",
            )
        )
        listed = self.client.get("/api/v1/sample-requests/?page=1&page_size=20")
        self.assertEqual(listed.status_code, 200, listed.data)
        row = next(item for item in listed.data["data"] if item["id"] == created.data["data"]["id"])
        color = row["products"][0]["color"]
        self.assertIn("标准色卡", color)
        self.assertIn("海军蓝", color)
        self.assertNotEqual(color, "")

    def test_list_search_product_names_deduplicates_requests(self):
        from ..models import SampleProduct

        created = self.create_sample()
        sample_id = created.data["data"]["id"]
        for line in (1, 2):
            SampleProduct.objects.create(
                sample_request_id=sample_id, line_number=line,
                product_name=f"折叠餐椅 {line}",
            )
        response = self.client.get("/api/v1/sample-requests/", {"q": "折叠餐椅"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["meta"]["total"], 1)
        self.assertEqual([row["id"] for row in response.data["data"]], [sample_id])
        missing = self.client.get("/api/v1/sample-requests/", {"q": "不存在的样品名称"})
        self.assertEqual(missing.data["data"], [])

    def test_list_search_legacy_item_names_and_dates(self):
        created = self.create_sample()
        sample_id = created.data["data"]["id"]
        response = self.client.get("/api/v1/sample-requests/", {"q": "测试样品"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row["id"] for row in response.data["data"]], [sample_id])
        now = timezone.now()
        included = self.client.get("/api/v1/sample-requests/", {
            "requested_from": (now - timedelta(days=1)).isoformat(),
            "requested_to": (now + timedelta(days=1)).isoformat(),
        })
        self.assertEqual(included.status_code, 200, included.data)
        self.assertEqual(included.data["meta"]["total"], 1)
        excluded = self.client.get("/api/v1/sample-requests/", {
            "requested_to": (now - timedelta(days=1)).isoformat(),
        })
        self.assertEqual(excluded.data["meta"]["total"], 0)
        invalid = self.client.get("/api/v1/sample-requests/", {"requested_from": "invalid"})
        self.assertEqual(invalid.status_code, 400)

    def test_list_product_search_preserves_data_scope_and_permission(self):
        from ..models import SampleProduct

        self.create_sample()
        hidden = SampleRequest.objects.create(
            request_number="HIDDEN-SAMPLE-SEARCH", customer_account=self.other_customer,
            owner_employee=self.other_employee, requested_at=timezone.now(),
        )
        SampleProduct.objects.create(sample_request=hidden, line_number=1, product_name="私有搜索产品")
        self.user.user_permissions.remove(Permission.objects.get(
            content_type__app_label="samples", codename="view_all_samplerequest",
        ))
        for name in ("_perm_cache", "_user_perm_cache"):
            if hasattr(self.user, name):
                delattr(self.user, name)
        response = self.client.get("/api/v1/sample-requests/", {"q": "私有搜索产品"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["meta"]["total"], 0)
        self.user.user_permissions.clear()
        for name in ("_perm_cache", "_user_perm_cache"):
            if hasattr(self.user, name):
                delattr(self.user, name)
        forbidden = self.client.get("/api/v1/sample-requests/", {"q": "私有搜索产品"})
        self.assertEqual(forbidden.status_code, 403)

    def test_list_returns_full_form_and_product_columns(self):
        created = self.create_sample_form()
        sample_id = created.data["data"]["id"]

        listed = self.client.get("/api/v1/sample-requests/")

        self.assertEqual(listed.status_code, 200, listed.data)
        row = next(item for item in listed.data["data"] if item["id"] == sample_id)
        self.assertEqual(row["request_number"], "HTS-FORM-001")
        self.assertEqual(row["manual_request_number"], "FORM-001")
        self.assertEqual(row["shipping_method_display"], "邮寄")
        self.assertEqual(row["delivery_batch_display"], "一次交货")
        self.assertEqual(row["sample_type_display"], "售前样")
        self.assertFalse(row["is_repeat_order"])
        self.assertEqual(row["created_by"]["id"], str(self.employee.pk))
        self.assertEqual(len(row["products"]), 1)
        product = row["products"][0]
        self.assertEqual(product["category_name"], self.product_category.category_name)
        self.assertEqual(product["product_name"], "休闲椅样品")
        self.assertEqual(product["specification"], "常规规格")
        self.assertEqual(product["task_sheet_file_name"], "task.png")
        self.assertEqual(product["total_sample_quantity"], 5)
        self.assertEqual(product["length_cm"], "80.00")
        self.assertIsNone(product["armrest_width_cm"])
        self.assertEqual(product["seat_width_cm"], "52.00")
        self.assertEqual(product["back_height_cm"], "45.00")
        self.assertEqual(product["seat_height_cm"], "48.00")

    def test_cross_customer_entity_and_unassigned_list_are_scoped(self):
        self.user.user_permissions.remove(
            Permission.objects.get(
                content_type__app_label="samples",
                codename="view_all_samplerequest",
            )
        )
        foreign_entity = CustomerTransactionEntity.objects.create(
            customer_account=self.other_customer,
            entity_code="FOREIGN_SAMPLE_ENTITY",
            legal_name="其他客户主体",
        )
        rejected = self.client.post(
            "/api/v1/sample-requests/",
            self.payload(transaction_entity_id=str(foreign_entity.pk)),
            format="json",
        )
        visible = self.create_sample()
        hidden = SampleRequest.objects.create(
            customer_account=self.other_customer,
            transaction_entity=foreign_entity,
            owner_employee=self.other_employee,
            request_number="HIDDEN_SAMPLE_REQUEST",
            requested_at=timezone.now(),
        )
        listed = self.client.get("/api/v1/sample-requests/")
        ids = {item["id"] for item in listed.data["data"]}

        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertIn("transaction_entity_id", rejected.data["error"]["field_errors"])
        self.assertIn(visible.data["data"]["id"], ids)
        self.assertNotIn(str(hidden.pk), ids)

    def test_item_changes_require_parent_etag_and_lock_after_submit(self):
        created = self.create_sample(items=[])
        sample_id = created.data["data"]["id"]
        added = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/items/",
            {
                "product_description_snapshot": "后加样品",
                "requested_quantity": "1.0000",
                "unit_code": "PCS",
            },
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        stale = self.client.patch(
            f"/api/v1/sample-items/{added.data['data']['id']}/",
            {"requested_quantity": "2.0000"},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        submitted = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=added.headers["ETag"],
        )
        locked = self.client.patch(
            f"/api/v1/sample-items/{added.data['data']['id']}/",
            {"requested_quantity": "3.0000"},
            format="json",
            HTTP_IF_MATCH=submitted.headers["ETag"],
        )

        self.assertEqual(added.status_code, 201, added.data)
        self.assertEqual(stale.status_code, 412, stale.data)
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(locked.status_code, 409, locked.data)

    def test_sam02_draft_detail_fields_and_collaborators_require_etag(self):
        created = self.create_sample()
        sample_id = created.data["data"]["id"]
        stale = self.client.patch(
            f"/api/v1/sample-requests/{sample_id}/",
            {"expected_shipped_at": timezone.now().isoformat()},
            format="json",
            HTTP_IF_MATCH='"stale"',
        )
        updated = self.client.patch(
            f"/api/v1/sample-requests/{sample_id}/",
            {
                "expected_shipped_at": timezone.now().isoformat(),
                "expected_received_at": (timezone.now() + timedelta(days=2)).isoformat(),
                "collaborator_employee_ids": [str(self.other_employee.pk)],
                "notes": "SAM-02 详情编辑测试",
            },
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )

        self.assertEqual(stale.status_code, 412, stale.data)
        self.assertEqual(updated.status_code, 200, updated.data)
        data = updated.data["data"]
        self.assertTrue(data["expected_shipped_at"])
        self.assertTrue(data["expected_received_at"])
        self.assertEqual(data["collaborators"][0]["id"], str(self.other_employee.pk))
        self.assertEqual(data["notes"], "SAM-02 详情编辑测试")

    def test_fee_decision_supersedes_history_and_evidence_requires_file(self):
        prepared = self.advance_to_preparing(self.create_sample())
        sample_id = prepared.data["data"]["id"]
        no_evidence = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/fee-records/",
            {
                "fee_decision": "PAID",
                "amount": "100.0000",
                "currency_code": "USD",
                "freight_bearer": "CUSTOMER",
                "verification_status": "EVIDENCE_UPLOADED",
            },
            format="json",
            HTTP_IF_MATCH=prepared.headers["ETag"],
        )
        free = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/fee-records/",
            {
                "fee_decision": "FREE",
                "amount": "0",
                "currency_code": "USD",
                "verification_status": "NOT_REQUIRED",
                "freight_bearer": "COMPANY",
                "decision_reason": "SAM-03 免费样业务支持",
                "free_confirmed_by_employee_id": str(self.employee.pk),
            },
            format="json",
            HTTP_IF_MATCH=prepared.headers["ETag"],
        )
        paid = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/fee-records/",
            {
                "fee_decision": "PAID",
                "amount": "100.0000",
                "currency_code": "USD",
                "freight_bearer": "CUSTOMER",
                "verification_status": "PENDING",
            },
            format="json",
            HTTP_IF_MATCH=free.headers["ETag"],
        )

        self.assertEqual(no_evidence.status_code, 409, no_evidence.data)
        self.assertEqual(free.status_code, 201, free.data)
        self.assertEqual(paid.status_code, 201, paid.data)
        records = SampleFeeRecord.objects.filter(sample_request_id=sample_id).order_by("created_at")
        self.assertIsNotNone(records[0].superseded_at)
        self.assertIsNone(records[1].superseded_at)

    def test_fee_waiver_requires_approval_and_updates_current_record(self):
        prepared = self.advance_to_preparing(self.create_sample())
        sample_id = prepared.data["data"]["id"]
        CustomerAssignment.objects.create(
            customer_account=self.customer,
            employee=self.other_employee,
            assignment_role="COLLABORATOR",
            effective_from=timezone.now(),
        )
        self.other_user.user_permissions.set(
            Permission.objects.filter(content_type__app_label__in=["samples", "workflow"])
        )
        waiver = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/fee-records/",
            {
                "fee_decision": "WAIVED",
                "currency_code": "USD",
                "sample_fee_amount": "120.0000",
                "shipping_fee_amount": "20.0000",
                "decision_reason": "SAM-03 联调：重点客户费用豁免",
                "approver_employee_id": str(self.other_employee.pk),
            },
            format="json",
            HTTP_IF_MATCH=prepared.headers["ETag"],
        )
        self.assertEqual(waiver.status_code, 201, waiver.data)
        self.assertEqual(waiver.data["data"]["fee_decision"], "PENDING")
        self.assertEqual(waiver.data["data"]["requested_decision"], "WAIVED")
        self.assertEqual(waiver.data["data"]["approval_status"], "PENDING")

        self.client.force_authenticate(user=self.other_user)
        detail = self.client.get(f"/api/v1/sample-requests/{sample_id}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        approval_id = detail.data["data"]["fee_approvals"][0]["approval_id"]
        approved = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/fee-approval/approve/",
            {"approval_id": approval_id, "note": "SAM-03 联调审批通过"},
            format="json",
            HTTP_IF_MATCH=detail.headers["ETag"],
        )
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data["data"]["fee_record"]["fee_decision"], "WAIVED")
        self.assertEqual(approved.data["data"]["approval"]["status"], "APPROVED")

    def test_fee_decision_requires_etag_and_rejects_manual_finance_confirmation(self):
        prepared = self.advance_to_preparing(self.create_sample())
        sample_id = prepared.data["data"]["id"]
        payload = {
            "fee_decision": "PAID",
            "currency_code": "USD",
            "sample_fee_amount": "100.0000",
            "freight_bearer": "CUSTOMER",
            "verification_status": "PENDING",
        }
        missing_etag = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/fee-records/",
            payload,
            format="json",
        )
        stale = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/fee-records/",
            payload,
            format="json",
            HTTP_IF_MATCH='"stale"',
        )
        manual_confirmation = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/fee-records/",
            {**payload, "verification_status": "MANUALLY_CONFIRMED"},
            format="json",
            HTTP_IF_MATCH=prepared.headers["ETag"],
        )
        self.assertEqual(missing_etag.status_code, 428, missing_etag.data)
        self.assertEqual(stale.status_code, 412, stale.data)
        self.assertEqual(manual_confirmation.status_code, 400, manual_confirmation.data)

    @patch("apps.samples.uploads._clamav_scan", return_value="ClamAV test clean")
    def test_payment_evidence_upload_scans_and_links_file_before_fee_confirmation(self, _scan):
        prepared = self.advance_to_preparing(self.create_sample())
        sample_id = prepared.data["data"]["id"]
        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            uploaded = self.client.post(
                f"/api/v1/sample-requests/{sample_id}/fee-evidence/",
                {
                    "file": SimpleUploadedFile(
                        "payment-proof.pdf",
                        b"%PDF-1.4\n%%EOF",
                        content_type="application/pdf",
                    )
                },
                format="multipart",
                HTTP_IF_MATCH=prepared.headers["ETag"],
            )

        self.assertEqual(uploaded.status_code, 201, uploaded.data)
        self.assertEqual(uploaded.data["data"]["file_role"], "FEE_EVIDENCE")
        self.assertEqual(uploaded.data["data"]["scan_status"], "CLEAN")
        self.assertTrue(BusinessFile.objects.filter(original_name="payment-proof.pdf", scan_status="CLEAN").exists())
        self.assertTrue(_scan.called)

        fee = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/fee-records/",
            {
                "fee_decision": "PAID",
                "currency_code": "USD",
                "sample_fee_amount": "100.0000",
                "freight_bearer": "CUSTOMER",
                "verification_status": "EVIDENCE_UPLOADED",
            },
            format="json",
            HTTP_IF_MATCH=uploaded.headers["ETag"],
        )
        self.assertEqual(fee.status_code, 201, fee.data)
        self.assertEqual(fee.data["data"]["verification_status"], "EVIDENCE_UPLOADED")

    def test_unconfirmed_paid_fee_requires_explicit_warning_and_reason(self):
        prepared = self.advance_to_preparing(self.create_sample())
        sample_id = prepared.data["data"]["id"]
        evidence_file = BusinessFile.objects.create(
            uploaded_by_employee=self.employee,
            original_name="fee-proof.png",
            storage_key="tests/samples/fee-proof.png",
            content_type="image/png",
            size_bytes=10,
            scan_status="CLEAN",
        )
        linked = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/files/",
            {"file_id": str(evidence_file.pk), "file_role": "FEE_EVIDENCE"},
            format="json",
            HTTP_IF_MATCH=prepared.headers["ETag"],
        )
        fee = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/fee-records/",
            {
                "fee_decision": "PAID",
                "amount": "100.0000",
                "currency_code": "USD",
                "freight_bearer": "CUSTOMER",
                "verification_status": "EVIDENCE_UPLOADED",
            },
            format="json",
            HTTP_IF_MATCH=linked.headers["ETag"],
        )
        prepared_after_fee = self.client.get(f"/api/v1/sample-requests/{sample_id}/")
        shipment = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/shipments/",
            {
                "items": [
                    {
                        "sample_item_id": prepared_after_fee.data["data"]["items"][0]["id"],
                        "shipped_quantity": "1.0000",
                    }
                ]
            },
            format="json",
            HTTP_IF_MATCH=prepared_after_fee.headers["ETag"],
        )
        ship_url = f"/api/v1/sample-shipments/{shipment.data['data']['id']}/ship/"
        ship_payload = {
            "address_id": str(self.address.pk),
            "contact_id": str(self.contact.pk),
            "carrier_code": "SF",
            "tracking_number": "SF123456",
        }
        blocked = self.client.post(
            ship_url,
            ship_payload,
            format="json",
            HTTP_IF_MATCH=shipment.headers["ETag"],
        )
        shipped = self.client.post(
            ship_url,
            {
                **ship_payload,
                "fee_warning_acknowledged": True,
                "fee_warning_reason": "客户已确认先寄样后核销费用",
            },
            format="json",
            HTTP_IF_MATCH=shipment.headers["ETag"],
        )

        self.assertEqual(fee.status_code, 201, fee.data)
        self.assertEqual(shipment.status_code, 201, shipment.data)
        self.assertEqual(blocked.status_code, 409, blocked.data)
        self.assertEqual(shipped.status_code, 200, shipped.data)
        self.assertTrue(shipped.data["data"]["fee_warning_acknowledged"])

    def test_full_ship_deliver_feedback_complete_flow_finishes_sla(self):
        SlaPolicy.objects.create(
            policy_code="SAMPLE_STANDARD",
            display_name="样品标准 SLA",
            target_type="SAMPLE_REQUEST",
            resolution_minutes=120,
            is_enabled=True,
        )
        prepared = self.advance_to_preparing(self.create_sample())
        sample_id = prepared.data["data"]["id"]
        fee = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/fee-records/",
            {
                "fee_decision": "FREE",
                "amount": "0",
                "currency_code": "USD",
                "verification_status": "NOT_REQUIRED",
                "freight_bearer": "COMPANY",
                "decision_reason": "SAM-03 免费样业务支持",
                "free_confirmed_by_employee_id": str(self.employee.pk),
            },
            format="json",
            HTTP_IF_MATCH=prepared.headers["ETag"],
        )
        current = self.client.get(f"/api/v1/sample-requests/{sample_id}/")
        shipment = self.create_shipment(current)
        ship = self.client.post(
            f"/api/v1/sample-shipments/{shipment.data['data']['id']}/ship/",
            {
                "address_id": str(self.address.pk),
                "contact_id": str(self.contact.pk),
                "carrier_code": "DHL",
                "tracking_number": "DHL123456",
            },
            format="json",
            HTTP_IF_MATCH=shipment.headers["ETag"],
        )
        delivered = self.client.post(
            f"/api/v1/sample-shipments/{shipment.data['data']['id']}/deliver/",
            {"note": "客户签收"},
            format="json",
            HTTP_IF_MATCH=ship.headers["ETag"],
        )
        feedback = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/feedback/",
            {
                "customer_contact_id": str(self.contact.pk),
                "feedback_type": "POSITIVE",
                "feedback_content": "样品测试通过",
                "occurred_at": timezone.now().isoformat(),
            },
            format="json",
            HTTP_IF_MATCH=delivered.headers["Sample-Request-ETag"],
        )
        completed = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/complete/",
            {},
            format="json",
            HTTP_IF_MATCH=feedback.headers["ETag"],
        )

        self.assertEqual(fee.status_code, 201, fee.data)
        self.assertEqual(ship.status_code, 200, ship.data)
        self.assertEqual(delivered.status_code, 200, delivered.data)
        self.assertEqual(feedback.status_code, 201, feedback.data)
        self.assertEqual(completed.status_code, 200, completed.data)
        self.assertEqual(completed.data["data"]["status"], SampleRequestStatus.CONFIRMED)
        tracking = SampleRequest.objects.get(pk=sample_id).sla_links.get().sla_tracking
        self.assertEqual(tracking.status, SlaTrackingStatus.MET)
        sla_list = self.client.get("/api/v1/sla-trackings/?target_type=SAMPLE_REQUEST")
        self.assertEqual(sla_list.status_code, 200, sla_list.data)
        self.assertEqual(sla_list.data["data"][0]["source"]["id"], sample_id)

    def test_update_shipment_material_progress_records_event_and_audit_trail(self):
        prepared = self.advance_to_preparing(self.create_sample())
        sample_id = prepared.data["data"]["id"]
        fee = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/fee-records/",
            {
                "fee_decision": "FREE",
                "amount": "0",
                "currency_code": "USD",
                "verification_status": "NOT_REQUIRED",
                "freight_bearer": "COMPANY",
                "decision_reason": "物料进度测试免费样",
                "free_confirmed_by_employee_id": str(self.employee.pk),
            },
            format="json",
            HTTP_IF_MATCH=prepared.headers["ETag"],
        )
        shipment = self.create_shipment(self.client.get(f"/api/v1/sample-requests/{sample_id}/"))
        shipped = self.client.post(
            f"/api/v1/sample-shipments/{shipment.data['data']['id']}/ship/",
            {
                "address_id": str(self.address.pk),
                "contact_id": str(self.contact.pk),
                "carrier_code": "DHL",
                "tracking_number": "PROGRESS001",
            },
            format="json",
            HTTP_IF_MATCH=shipment.headers["ETag"],
        )
        progress_url = f"/api/v1/sample-shipments/{shipment.data['data']['id']}/progress/"
        missing_material_status = self.client.post(
            progress_url,
            {"occurred_at": timezone.now().isoformat(), "material_status": ""},
            format="json",
            HTTP_IF_MATCH=shipped.headers["ETag"],
        )
        progress_at = timezone.now() - timedelta(minutes=15)
        progress = self.client.post(
            progress_url,
            {
                "occurred_at": progress_at.isoformat(),
                "material_status": "物料已到达转运中心，等待清关。",
            },
            format="json",
            HTTP_IF_MATCH=shipped.headers["ETag"],
        )

        self.assertEqual(fee.status_code, 201, fee.data)
        self.assertEqual(shipped.status_code, 200, shipped.data)
        self.assertEqual(missing_material_status.status_code, 400, missing_material_status.data)
        self.assertEqual(progress.status_code, 200, progress.data)
        self.assertTrue(progress.headers["ETag"])
        self.assertTrue(progress.headers["Sample-Request-ETag"])
        progress_event = next(
            event for event in progress.data["data"]["events"] if event["event_type"] == "PROGRESS"
        )
        self.assertEqual(progress_event["payload_snapshot"]["material_status"], "物料已到达转运中心，等待清关。")
        self.assertEqual(parse_datetime(progress_event["occurred_at"]), progress_at)
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="SAMPLE_REQUEST",
                object_id=sample_id,
                action="SHIPMENT_PROGRESS_UPDATED",
            ).exists()
        )
        self.assertTrue(
            CustomerTimelineEvent.objects.filter(
                customer_account=self.customer,
                source_id=sample_id,
                event_type="SAMPLE_SHIPMENT_PROGRESS_UPDATED",
            ).exists()
        )

    def test_sam04_delivery_event_feedback_task_and_formal_confirmation(self):
        prepared = self.advance_to_preparing(self.create_sample(sample_type="TESTING"))
        sample_id = prepared.data["data"]["id"]
        fee = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/fee-records/",
            {
                "fee_decision": "FREE",
                "amount": "0",
                "currency_code": "USD",
                "verification_status": "NOT_REQUIRED",
                "freight_bearer": "COMPANY",
                "decision_reason": "SAM-04 联调免费样",
                "free_confirmed_by_employee_id": str(self.employee.pk),
            },
            format="json",
            HTTP_IF_MATCH=prepared.headers["ETag"],
        )
        shipment = self.create_shipment(self.client.get(f"/api/v1/sample-requests/{sample_id}/"))
        shipped = self.client.post(
            f"/api/v1/sample-shipments/{shipment.data['data']['id']}/ship/",
            {
                "address_id": str(self.address.pk),
                "contact_id": str(self.contact.pk),
                "carrier_code": "DHL",
                "tracking_number": "SAM04DHL001",
            },
            format="json",
            HTTP_IF_MATCH=shipment.headers["ETag"],
        )
        delivered = self.client.post(
            f"/api/v1/sample-shipments/{shipment.data['data']['id']}/deliver/",
            {"note": "SAM-04 人工签收联调"},
            format="json",
            HTTP_IF_MATCH=shipped.headers["ETag"],
        )
        self.assertEqual(fee.status_code, 201, fee.data)
        self.assertEqual(shipped.status_code, 200, shipped.data)
        self.assertEqual(delivered.status_code, 200, delivered.data)
        self.assertEqual(delivered.data["data"]["status"], "DELIVERED")
        self.assertEqual(
            SampleRequest.objects.get(pk=sample_id).status,
            SampleRequestStatus.FEEDBACK_PENDING,
        )
        self.assertEqual(delivered.data["data"]["events"][0]["source"], "MANUAL")
        self.assertEqual(SampleShipmentEvent.objects.filter(sample_shipment_id=shipment.data["data"]["id"]).count(), 2)
        self.assertEqual(BusinessTask.objects.filter(automation_key__startswith="SAMPLE_DELIVERED_FEEDBACK:").count(), 1)
        shipment_detail = self.client.get(f"/api/v1/sample-shipments/{shipment.data['data']['id']}/")
        self.assertEqual(shipment_detail.status_code, 200, shipment_detail.data)
        self.assertTrue(shipment_detail.headers["ETag"])
        self.assertEqual(len(shipment_detail.data["data"]["events"]), 2)

        duplicate_delivery = self.client.post(
            f"/api/v1/sample-shipments/{shipment.data['data']['id']}/deliver/",
            {"note": "重复事件"},
            format="json",
            HTTP_IF_MATCH=delivered.headers["ETag"],
        )
        self.assertEqual(duplicate_delivery.status_code, 409, duplicate_delivery.data)
        self.assertEqual(BusinessTask.objects.filter(automation_key__startswith="SAMPLE_DELIVERED_FEEDBACK:").count(), 1)

        invalid_feedback = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/feedback/",
            {
                "feedback_type": "NEGATIVE",
                "feedback_content": "客户反馈未通过",
                "occurred_at": timezone.now().isoformat(),
            },
            format="json",
            HTTP_IF_MATCH=delivered.headers["Sample-Request-ETag"],
        )
        self.assertEqual(invalid_feedback.status_code, 400, invalid_feedback.data)

        formal_feedback = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/feedback/",
            {
                "customer_contact_id": str(self.contact.pk),
                "feedback_type": "POSITIVE",
                "feedback_content": "客户确认产前样通过",
                "occurred_at": timezone.now().isoformat(),
                "confirmation_source": "CUSTOMER",
                "source_object_version": 2,
            },
            format="json",
            HTTP_IF_MATCH=delivered.headers["Sample-Request-ETag"],
        )
        self.assertEqual(formal_feedback.status_code, 201, formal_feedback.data)
        self.assertEqual(formal_feedback.data["data"]["confirmation_result"], "PASSED")
        self.assertEqual(formal_feedback.data["data"]["confirmation_source_display"], "客户确认")
        self.assertEqual(
            BusinessTask.objects.get(automation_key__startswith="SAMPLE_DELIVERED_FEEDBACK:").status,
            TaskStatus.COMPLETED,
        )

        completed = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/complete/",
            {},
            format="json",
            HTTP_IF_MATCH=formal_feedback.headers["ETag"],
        )
        self.assertEqual(completed.status_code, 200, completed.data)

    def test_submit_without_items_and_complete_without_feedback_are_rejected(self):
        empty = self.create_sample(items=[])
        submit = self.client.post(
            f"/api/v1/sample-requests/{empty.data['data']['id']}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=empty.headers["ETag"],
        )
        sample_request = SampleRequest.objects.create(
            customer_account=self.customer,
            transaction_entity=self.entity,
            customer_contact=self.contact,
            owner_employee=self.employee,
            request_number="NO_FEEDBACK_SAMPLE",
            requested_at=timezone.now(),
        )
        sample_request.items.create(
            line_number=1,
            product_description_snapshot="测试",
            requested_quantity=1,
            unit_code="PCS",
        )
        sample_request.status = SampleRequestStatus.FEEDBACK_PENDING
        sample_request.save(update_fields=["status", "updated_at"])
        detail = self.client.get(f"/api/v1/sample-requests/{sample_request.pk}/")
        complete = self.client.post(
            f"/api/v1/sample-requests/{sample_request.pk}/complete/",
            {},
            format="json",
            HTTP_IF_MATCH=detail.headers["ETag"],
        )

        self.assertEqual(submit.status_code, 409, submit.data)
        self.assertEqual(complete.status_code, 409, complete.data)
