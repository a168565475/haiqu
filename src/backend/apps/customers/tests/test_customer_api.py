from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.crm.models import CommunicationTaskLink, CustomerCommunication, CustomerTimelineEvent
from apps.organizations.models import Employee, EmployeeOrganizationAssignment, OrganizationUnit
from apps.quotations.models import (
    Quotation,
    QuotationLine,
    QuotationOutcomeStatus,
    QuotationVersion,
    QuotationVersionStatus,
)
from apps.reference_data.models import ReferenceDictionary
from apps.sales_orders.models import SalesOrder, SalesOrderSource, SalesOrderStatus
from apps.workflow.models import BusinessTask

from ..models import (
    CustomerAccount,
    CustomerActivityReview,
    CustomerAssignment,
    CustomerBusinessSnapshot,
    CustomerContact,
    CustomerDataAccessGrant,
    CustomerGradeReview,
    CustomerTag,
    CustomerTaskLink,
    CustomerTransactionEntity,
)


class CustomerApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="customer_api_user",
            password="StrongTestPassword123!",
        )
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="CUSTOMER_API_USER",
            display_name="客户接口测试员工",
        )
        self.other_user = user_model.objects.create_user(username="customer_api_other")
        self.other_employee = Employee.objects.create(
            user=self.other_user,
            employee_code="CUSTOMER_API_OTHER",
            display_name="其他测试员工",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(content_type__app_label="customers").exclude(
                codename="view_all_customer"
            )
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.website_source = ReferenceDictionary.objects.get(
            category_code="CUSTOMER_SOURCE",
            item_code="ALIBABA_INTERNATIONAL",
        )

    def create_customer(self, code, name, owner=None):
        customer = CustomerAccount.objects.create(
            account_code=code,
            account_name=name,
            primary_country_code="CN",
        )
        CustomerAssignment.objects.create(
            customer_account=customer,
            employee=owner or self.employee,
            assignment_role="PRIMARY_OWNER",
            effective_from=timezone.now(),
        )
        return customer

    def test_customer_list_uses_effective_sales_orders_for_rolling_sales_and_latest_order(self):
        customer = self.create_customer("ORDER_METRICS", "订单指标客户")
        today = timezone.localdate()

        def make_order(number, *, days_ago, status, amount, rate="1.000000"):
            return SalesOrder.objects.create(
                order_number=number,
                source_type=SalesOrderSource.DIRECT,
                customer_account=customer,
                salesperson=self.employee,
                order_date=today - timedelta(days=days_ago),
                currency_code="USD" if rate != "1.000000" else "CNY",
                exchange_rate=rate,
                status=status,
                total_amount=amount,
            )

        make_order(
            "SO-METRIC-001",
            days_ago=40,
            status=SalesOrderStatus.CONFIRMED,
            amount="100.0000",
            rate="7.000000",
        )
        latest = make_order(
            "SO-METRIC-002",
            days_ago=2,
            status=SalesOrderStatus.FULFILLING,
            amount="300.0000",
        )
        make_order(
            "SO-METRIC-DRAFT",
            days_ago=1,
            status=SalesOrderStatus.DRAFT,
            amount="9999.0000",
        )
        make_order(
            "SO-METRIC-OLD",
            days_ago=500,
            status=SalesOrderStatus.COMPLETED,
            amount="8888.0000",
        )
        make_order(
            "SO-METRIC-FUTURE",
            days_ago=-10,
            status=SalesOrderStatus.CONFIRMED,
            amount="7777.0000",
        )
        entity = CustomerTransactionEntity.objects.create(
            customer_account=customer,
            entity_code="ORDER_METRICS_ENTITY",
            legal_name="订单指标客户",
        )
        for index, outcome_status in enumerate(
            [
                QuotationOutcomeStatus.WON,
                QuotationOutcomeStatus.WON,
                QuotationOutcomeStatus.OPEN,
                QuotationOutcomeStatus.CANCELLED,
            ],
            start=1,
        ):
            quotation = Quotation.objects.create(
                customer_account=customer,
                transaction_entity=entity,
                owner_employee=self.employee,
                quotation_number=f"QUOTE-METRIC-{index:03d}",
                subject=f"指标报价 {index}",
            )
            if outcome_status == QuotationOutcomeStatus.WON:
                accepted_version = QuotationVersion.objects.create(
                    quotation=quotation,
                    version_number=1,
                    currency_code="CNY",
                )
                QuotationLine.objects.create(
                    quotation_version=accepted_version,
                    line_number=1,
                    product_description_snapshot="指标测试产品",
                    quantity="1.0000",
                    unit_code="PCS",
                )
                accepted_version.status = QuotationVersionStatus.SENT
                accepted_version.locked_at = timezone.now()
                accepted_version.transaction_entity_snapshot = {"legal_name": entity.legal_name}
                accepted_version.address_snapshot = {"address_line1": "测试地址"}
                accepted_version.contact_snapshot = {"display_name": "测试联系人"}
                accepted_version.save(
                    update_fields=[
                        "status",
                        "locked_at",
                        "transaction_entity_snapshot",
                        "address_snapshot",
                        "contact_snapshot",
                        "updated_at",
                    ]
                )
                quotation.outcome_status = outcome_status
                quotation.accepted_version = accepted_version
                quotation.save(update_fields=["outcome_status", "accepted_version", "updated_at"])
            elif outcome_status != QuotationOutcomeStatus.OPEN:
                quotation.outcome_status = outcome_status
                quotation.save(update_fields=["outcome_status", "updated_at"])

        response = self.client.get("/api/v1/customers/")
        detail = self.client.get(f"/api/v1/customers/{customer.pk}/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(detail.status_code, 200, detail.data)
        row = next(item for item in response.data["data"] if item["id"] == str(customer.pk))
        self.assertEqual(row["lifetime_sales_amount"], "9888.0000")
        self.assertEqual(row["lifetime_sales_order_count"], 3)
        self.assertEqual(row["last_12m_sales_amount"], "1000.0000")
        self.assertEqual(row["last_12m_sales_order_count"], 2)
        self.assertEqual(row["quotation_conversion_rate"], "66.67")
        self.assertEqual(row["recent_order"]["id"], str(latest.pk))
        self.assertEqual(row["recent_order"]["order_number"], latest.order_number)
        self.assertEqual(row["recent_order"]["status_display"], "履约中")
        self.assertEqual(detail.data["data"]["lifetime_sales_amount"], "9888.0000")
        self.assertEqual(detail.data["data"]["quotation_conversion_rate"], "66.67")

    def test_create_customer_generates_number_owner_audit_and_timeline(self):
        response = self.client.post(
            "/api/v1/customers/",
            {
                "account_name": "新建客户",
                "primary_country_code": "CN",
                "customer_source_item_id": str(self.website_source.pk),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        customer = CustomerAccount.objects.get(pk=response.data["data"]["id"])
        self.assertRegex(customer.account_code, r"^CUS-\d{6,}$")
        self.assertTrue(
            customer.assignments.filter(
                employee=self.employee,
                assignment_role="PRIMARY_OWNER",
                effective_to__isnull=True,
            ).exists()
        )
        self.assertEqual(customer.source_attributions.get().source_item, self.website_source)
        self.assertEqual(customer.activity_reviews.get().activity_status, "INSUFFICIENT_DATA")
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="CUSTOMER_ACCOUNT",
                object_id=customer.pk,
                action="CREATED",
            ).exists()
        )
        self.assertTrue(
            CustomerTimelineEvent.objects.filter(
                customer_account=customer,
                event_type="CUSTOMER_CREATED",
            ).exists()
        )
        self.assertIn("ETag", response)

    def test_create_customer_accepts_domain_and_optional_contact(self):
        response = self.client.post(
            "/api/v1/customers/",
            {
                "account_name": "域名客户",
                "primary_country_code": "DE",
                "primary_website_url": "example.de",
                "customer_source_item_id": str(self.website_source.pk),
                "contact_name": "采购经理",
                "contact_method_type": "EMAIL",
                "contact_method_value": "Buyer@Example.de",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        customer = CustomerAccount.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(customer.primary_website_url, "https://example.de")
        method = customer.contacts.get().methods.get()
        self.assertEqual(method.normalized_value, "buyer@example.de")

    def test_permanently_delete_customer_cascades_contact_and_task(self):
        customer = self.create_customer("DELETE_CASCADE", "待永久删除客户")
        contact = CustomerContact.objects.create(
            customer_account=customer,
            display_name="待永久删除联系人",
        )
        task = BusinessTask.objects.create(
            assignee_employee=self.employee,
            created_by_employee=self.employee,
            title="待永久删除任务",
        )
        CustomerTaskLink.objects.create(
            customer_account=customer,
            business_task=task,
            is_primary_source=True,
        )

        url = f"/api/v1/customers/{customer.pk}/"
        etag = self.client.get(url).headers["ETag"]
        response = self.client.delete(url, HTTP_IF_MATCH=etag)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertGreater(response.data["data"]["deleted_count"], 0)
        self.assertFalse(CustomerAccount.objects.filter(pk=customer.pk).exists())
        self.assertFalse(CustomerContact.objects.filter(pk=contact.pk).exists())
        self.assertFalse(BusinessTask.objects.filter(pk=task.pk).exists())

    def test_customer_options_and_duplicate_check(self):
        existing = self.create_customer("DUPLICATE_CHECK", "海趣贸易有限公司")
        existing.primary_website_url = "https://www.haiqu.example"
        existing.save(update_fields=["primary_website_url", "updated_at"])

        options = self.client.get("/api/v1/customers/options/")
        published_sources = self.client.get(
            "/api/v1/reference-data/options/CUSTOMER_SOURCE/"
        )
        duplicate = self.client.get(
            "/api/v1/customers/duplicate-check/",
            {
                "name": "海趣贸易有限公司",
                "website": "haiqu.example",
                "country_code": "CN",
            },
        )

        self.assertEqual(options.status_code, 200, options.data)
        self.assertTrue(options.data["data"]["customer_sources"])
        self.assertEqual(published_sources.status_code, 200, published_sources.data)
        self.assertSetEqual(
            {
                item["item_code"]
                for item in options.data["data"]["customer_sources"]
            },
            {item["code"] for item in published_sources.data["data"]},
        )
        self.assertTrue(options.data["data"]["owner_options"])
        self.assertIn(
            ("TH", "泰国"),
            {
                (item["item_code"], item["display_name"])
                for item in options.data["data"]["country_options"]
            },
        )
        self.assertEqual(duplicate.status_code, 200, duplicate.data)
        self.assertTrue(duplicate.data["data"]["has_high_risk_match"])
        self.assertEqual(duplicate.data["data"]["matches"][0]["customer_id"], str(existing.pk))

    def test_create_customer_tag_validates_and_writes_audit(self):
        created = self.client.post(
            "/api/v1/customers/tags/",
            {"tag_name": "东南亚重点", "color": "#2563EB"},
            format="json",
        )
        duplicate = self.client.post(
            "/api/v1/customers/tags/",
            {"tag_name": "东南亚重点", "color": "#2563EB"},
            format="json",
        )
        invalid_color = self.client.post(
            "/api/v1/customers/tags/",
            {"tag_name": "颜色错误", "color": "blue"},
            format="json",
        )

        self.assertEqual(created.status_code, 201, created.data)
        customer_tag = CustomerTag.objects.get(pk=created.data["data"]["id"])
        self.assertTrue(customer_tag.tag_code.startswith("CUSTOM_"))
        self.assertEqual(customer_tag.tag_name, "东南亚重点")
        self.assertEqual(customer_tag.color, "#2563EB")
        self.assertEqual(duplicate.status_code, 400, duplicate.data)
        self.assertEqual(invalid_color.status_code, 400, invalid_color.data)
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="CUSTOMER_TAG",
                object_id=customer_tag.pk,
                action="CREATED",
            ).exists()
        )

    def test_customer_entity_can_keep_multiple_addresses(self):
        customer = self.create_customer("MULTI_ADDRESS", "多地址客户")
        entity = CustomerTransactionEntity.objects.create(
            customer_account=customer,
            entity_code="MULTI_ADDRESS_ENTITY",
            legal_name="多地址客户主体",
        )
        address_url = f"/api/v1/customer-entities/{entity.pk}/addresses/"

        office = self.client.post(
            address_url,
            {
                "address_code": "OFFICE_001",
                "label": "办公地址",
                "country_code": "CN",
                "city": "深圳",
                "address_line1": "南山区办公路1号",
                "is_verified": False,
            },
            format="json",
        )
        shipping = self.client.post(
            address_url,
            {
                "address_code": "SHIPPING_001",
                "label": "收货地址",
                "country_code": "CN",
                "city": "东莞",
                "address_line1": "松山湖收货路2号",
                "is_verified": False,
            },
            format="json",
        )
        listing = self.client.get(address_url)

        self.assertEqual(office.status_code, 201, office.data)
        self.assertEqual(shipping.status_code, 201, shipping.data)
        self.assertEqual(listing.status_code, 200, listing.data)
        self.assertEqual(len(listing.data["data"]), 2)
        self.assertEqual(
            {item["address_code"] for item in listing.data["data"]},
            {"OFFICE_001", "SHIPPING_001"},
        )

    def test_customer_list_dashboard_fields_stats_export_and_bulk_tags(self):
        customer = self.create_customer("LIST_DASHBOARD", "列表看板客户")
        now = timezone.now()
        grade_a = ReferenceDictionary.objects.get(category_code="CUSTOMER_GRADE", item_code="A")
        CustomerGradeReview.objects.create(
            customer_account=customer,
            grade_item=grade_a,
            reviewed_by_employee=self.employee,
            reason="重点客户",
            effective_from=now,
        )
        CustomerActivityReview.objects.create(
            customer_account=customer,
            activity_status="HIGH_RISK",
            reviewed_by_employee=self.employee,
            reason="需要及时跟进",
            effective_from=now,
        )
        CustomerBusinessSnapshot.objects.create(
            customer_account=customer,
            source_type="MANUAL",
            as_of_at=now,
            currency_code="USD",
            customer_total_value="128400.00",
            entered_by_employee=self.employee,
        )
        communication = CustomerCommunication.objects.create(
            customer_account=customer,
            created_by_employee=self.employee,
            communication_type="EMAIL",
            direction="OUTBOUND",
            content="客户跟进",
            occurred_at=now,
        )
        task = BusinessTask.objects.create(
            assignee_employee=self.employee,
            created_by_employee=self.employee,
            title="今日跟进客户",
            due_at=now,
        )
        CustomerTaskLink.objects.create(customer_account=customer, business_task=task)

        listing = self.client.get("/api/v1/customers/")
        stats = self.client.get("/api/v1/customers/stats/")
        export = self.client.get("/api/v1/customers/export/")
        tag = CustomerTag.objects.get(tag_code="KEY_CUSTOMER")
        bulk_tag = self.client.post(
            "/api/v1/customers/bulk-add-tags/",
            {"customer_ids": [str(customer.pk)], "customer_tag_ids": [str(tag.pk)], "reason": "批量维护标签"},
            format="json",
        )

        self.assertEqual(listing.status_code, 200, listing.data)
        row = listing.data["data"][0]
        self.assertIsNotNone(row["last_contact_at"])
        self.assertIsNotNone(row["next_follow_up_at"])
        self.assertEqual(row["customer_value"]["customer_total_value"], "128400.00")
        self.assertEqual(stats.status_code, 200, stats.data)
        self.assertEqual(stats.data["data"]["high_value"], 1)
        self.assertEqual(stats.data["data"]["high_risk"], 1)
        self.assertEqual(stats.data["data"]["today_follow_up"], 1)
        self.assertEqual(export.status_code, 200)
        self.assertIn("列表看板客户", export.content.decode("utf-8-sig"))
        self.assertEqual(bulk_tag.status_code, 200, bulk_tag.data)
        self.assertEqual(bulk_tag.data["data"]["updated_count"], 1)
        self.assertTrue(customer.tag_assignments.filter(customer_tag=tag, effective_to__isnull=True).exists())

    def test_duplicate_check_does_not_expose_inaccessible_customer(self):
        hidden = self.create_customer("HIDDEN_DUPLICATE", "不可见重复客户", owner=self.other_employee)
        hidden.primary_website_url = "https://private.example"
        hidden.save(update_fields=["primary_website_url", "updated_at"])

        response = self.client.get(
            "/api/v1/customers/duplicate-check/",
            {"name": "不可见重复客户", "website": "private.example", "country_code": "CN"},
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["matches"], [])

    def test_profile_history_and_manual_business_snapshot(self):
        customer = self.create_customer("PROFILE_HISTORY", "客户画像测试")
        grade_a = ReferenceDictionary.objects.get(category_code="CUSTOMER_GRADE", item_code="A")

        grade = self.client.post(
            f"/api/v1/customers/{customer.pk}/set-grade/",
            {"grade_item_id": str(grade_a.pk), "reason": "年度重点客户"},
            format="json",
        )
        activity = self.client.post(
            f"/api/v1/customers/{customer.pk}/set-activity/",
            {"activity_status": "FOLLOW_UP", "reason": "超过约定跟进时间"},
            format="json",
        )
        snapshot = self.client.post(
            f"/api/v1/customers/{customer.pk}/set-business-snapshot/",
            {
                "as_of_at": timezone.now().isoformat(),
                "currency_code": "USD",
                "last_12m_order_amount": "120000.00",
                "last_12m_order_count": 8,
                "quote_conversion_rate": "35.50",
                "notes": "人工录入，待订单模块接入后替换",
            },
            format="json",
        )

        self.assertEqual(grade.status_code, 201, grade.data)
        self.assertEqual(activity.status_code, 201, activity.data)
        self.assertEqual(snapshot.status_code, 201, snapshot.data)
        self.assertEqual(snapshot.data["data"]["source_type"], "MANUAL")
        self.assertEqual(CustomerActivityReview.objects.filter(customer_account=customer).count(), 1)
        self.assertTrue(CustomerBusinessSnapshot.objects.get(customer_account=customer).is_current)

    def test_source_history_classification_and_filters(self):
        customer = self.create_customer("CLASSIFICATION", "分类筛选客户")
        canton_fair = ReferenceDictionary.objects.get(
            category_code="CUSTOMER_SOURCE", item_code="CANTON_FAIR"
        )
        potential_customer = ReferenceDictionary.objects.get(
            category_code="CUSTOMER_TYPE", item_code="POTENTIAL"
        )
        customer_tag = CustomerTag.objects.get(tag_code="EUROPE_MARKET")

        first_source = self.client.post(
            f"/api/v1/customers/{customer.pk}/set-source/",
            {"source_item_id": str(self.website_source.pk), "notes": "首次来源"},
            format="json",
        )
        latest_source = self.client.post(
            f"/api/v1/customers/{customer.pk}/set-source/",
            {"source_item_id": str(canton_fair.pk), "notes": "近期广交会"},
            format="json",
        )
        classification = self.client.post(
            f"/api/v1/customers/{customer.pk}/set-classification/",
            {
                "customer_type_item_ids": [str(potential_customer.pk)],
                "customer_tag_ids": [str(customer_tag.pk)],
                "reason": "客户资料复核",
            },
            format="json",
        )
        filtered = self.client.get(
            "/api/v1/customers/",
            {"customer_source": "CANTON_FAIR", "customer_type": "POTENTIAL", "customer_tag": "EUROPE_MARKET"},
        )

        self.assertEqual(first_source.status_code, 201, first_source.data)
        self.assertEqual(latest_source.status_code, 201, latest_source.data)
        self.assertEqual(classification.status_code, 200, classification.data)
        self.assertEqual([item["id"] for item in filtered.data["data"]], [str(customer.pk)])
        history = customer.source_attributions.order_by("effective_from")
        self.assertEqual(history.count(), 2)
        self.assertIsNotNone(history.first().effective_to)
        self.assertIsNone(history.last().effective_to)

    def test_customer_list_only_contains_assigned_customers(self):
        visible = self.create_customer("VISIBLE_CUSTOMER", "可见客户")
        hidden = self.create_customer(
            "HIDDEN_CUSTOMER",
            "不可见客户",
            owner=self.other_employee,
        )

        response = self.client.get("/api/v1/customers/")

        self.assertEqual(response.status_code, 200, response.data)
        returned_ids = {item["id"] for item in response.data["data"]}
        self.assertIn(str(visible.pk), returned_ids)
        self.assertNotIn(str(hidden.pk), returned_ids)

    def test_customer_list_supports_q_organization_and_archived_filters(self):
        organization = OrganizationUnit.objects.create(
            unit_code="CUSTOMER_API_TEAM",
            unit_name="客户接口测试组",
        )
        EmployeeOrganizationAssignment.objects.create(
            employee=self.employee,
            organization_unit=organization,
            is_primary=True,
            effective_from=timezone.now(),
        )
        active = self.create_customer("FILTER_ACTIVE", "阿尔法客户")
        archived = self.create_customer("FILTER_ARCHIVED", "贝塔客户")
        archived.archived_at = timezone.now()
        archived.archived_by_employee = self.employee
        archived.archive_reason = "筛选测试"
        archived.save()

        searched = self.client.get("/api/v1/customers/", {"q": "阿尔法"})
        by_organization = self.client.get(
            "/api/v1/customers/",
            {"organization_id": str(organization.pk)},
        )
        archived_only = self.client.get("/api/v1/customers/", {"archived": "true"})

        self.assertEqual(
            [item["id"] for item in searched.data["data"]],
            [str(active.pk)],
        )
        self.assertEqual(
            [item["id"] for item in by_organization.data["data"]],
            [str(active.pk)],
        )
        self.assertEqual(
            [item["id"] for item in archived_only.data["data"]],
            [str(archived.pk)],
        )

    def test_customer_update_requires_current_etag(self):
        customer = self.create_customer("ETAG_API_CUSTOMER", "修改前")
        detail_url = f"/api/v1/customers/{customer.pk}/"
        allowed_origin = settings.CORS_ALLOWED_ORIGINS[0]
        detail = self.client.get(detail_url, HTTP_ORIGIN=allowed_origin)
        etag = detail.headers["ETag"]
        preflight = self.client.options(
            detail_url,
            HTTP_ORIGIN=allowed_origin,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="PATCH",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,if-match",
        )

        missing = self.client.patch(detail_url, {"account_name": "缺少条件"}, format="json")
        stale = self.client.patch(
            detail_url,
            {"account_name": "过期条件"},
            format="json",
            HTTP_IF_MATCH='"stale"',
        )
        success = self.client.patch(
            detail_url,
            {"account_name": "修改后"},
            format="json",
            HTTP_IF_MATCH=etag,
        )
        empty = self.client.patch(
            detail_url,
            {},
            format="json",
            HTTP_IF_MATCH=success.headers["ETag"],
        )

        self.assertEqual(missing.status_code, 428)
        self.assertEqual(stale.status_code, 412)
        self.assertEqual(success.status_code, 200, success.data)
        self.assertEqual(empty.status_code, 400, empty.data)
        self.assertIn("ETag", detail.headers["Access-Control-Expose-Headers"])
        self.assertEqual(preflight.status_code, 200)
        self.assertIn("if-match", preflight.headers["Access-Control-Allow-Headers"])
        customer.refresh_from_db()
        self.assertEqual(customer.account_name, "修改后")
        self.assertNotEqual(success.headers["ETag"], etag)

    def test_customer_archive_and_restore(self):
        customer = self.create_customer("ARCHIVE_CUSTOMER", "归档客户")
        url = f"/api/v1/customers/{customer.pk}/"
        etag = self.client.get(url).headers["ETag"]

        archived = self.client.post(
            f"{url}archive/",
            {"reason": "测试归档"},
            format="json",
            HTTP_IF_MATCH=etag,
        )
        restored = self.client.post(
            f"{url}restore/",
            {},
            format="json",
            HTTP_IF_MATCH=archived.headers["ETag"],
        )

        self.assertEqual(archived.status_code, 200, archived.data)
        self.assertEqual(restored.status_code, 200, restored.data)
        customer.refresh_from_db()
        self.assertIsNone(customer.archived_at)
        self.assertEqual(customer.archive_reason, "")

    def test_archived_customer_rejects_new_nested_records(self):
        customer = self.create_customer("LOCKED_CUSTOMER", "已归档客户")
        customer.archived_at = timezone.now()
        customer.archived_by_employee = self.employee
        customer.archive_reason = "停止维护"
        customer.save()

        response = self.client.post(
            f"/api/v1/customers/{customer.pk}/contacts/",
            {"display_name": "不应创建"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)

    def test_contact_rejects_transaction_entity_from_another_customer(self):
        customer = self.create_customer("CONTACT_CUSTOMER_A", "客户甲")
        other_customer = self.create_customer("CONTACT_CUSTOMER_B", "客户乙")
        foreign_entity = CustomerTransactionEntity.objects.create(
            customer_account=other_customer,
            entity_code="FOREIGN_ENTITY",
            legal_name="其他客户主体",
        )

        response = self.client.post(
            f"/api/v1/customers/{customer.pk}/contacts/",
            {
                "display_name": "跨客户联系人",
                "transaction_entity": str(foreign_entity.pk),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("transaction_entity", response.data["error"]["field_errors"])

    def test_contact_method_is_normalized_and_audited(self):
        customer = self.create_customer("METHOD_CUSTOMER", "联系方式客户")
        contact = CustomerContact.objects.create(
            customer_account=customer,
            display_name="采购联系人",
        )

        response = self.client.post(
            f"/api/v1/contacts/{contact.pk}/methods/",
            {
                "method_type": "PHONE",
                "raw_value": "+86 138-0013-8000",
                "is_primary": True,
                "is_preferred": True,
                "verification_status": "UNVERIFIED",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["normalized_value"], "+8613800138000")
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="CUSTOMER_CONTACT_METHOD",
                object_id=response.data["data"]["id"],
                action="CREATED",
            ).exists()
        )

    def test_effective_role_end_requires_etag_and_writes_audit(self):
        customer = self.create_customer("ROLE_CUSTOMER", "角色客户")
        entity = CustomerTransactionEntity.objects.create(
            customer_account=customer,
            entity_code="ROLE_ENTITY",
            legal_name="角色主体",
        )
        created = self.client.post(
            f"/api/v1/customer-entities/{entity.pk}/roles/",
            {"role_type": "CONTRACTING"},
            format="json",
        )
        role_id = created.data["data"]["id"]
        role_url = f"/api/v1/customer-entity-roles/{role_id}/"
        etag = self.client.get(role_url).headers["ETag"]

        missing = self.client.post(f"{role_url}end/", {}, format="json")
        ended = self.client.post(
            f"{role_url}end/",
            {},
            format="json",
            HTTP_IF_MATCH=etag,
        )

        self.assertEqual(missing.status_code, 428)
        self.assertEqual(ended.status_code, 200, ended.data)
        self.assertIsNotNone(ended.data["data"]["effective_to"])
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="CUSTOMER_TRANSACTION_ENTITY_ROLE",
                object_id=role_id,
                action="ENDED",
            ).exists()
        )

    def test_customer_360_summary_counts_core_records(self):
        customer = self.create_customer("SUMMARY_CUSTOMER", "汇总客户")
        CustomerTransactionEntity.objects.create(
            customer_account=customer,
            entity_code="SUMMARY_ENTITY",
            legal_name="汇总主体",
        )
        CustomerContact.objects.create(customer_account=customer, display_name="汇总联系人")

        response = self.client.get(f"/api/v1/customers/{customer.pk}/summary/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["counts"]["entities"], 1)
        self.assertEqual(response.data["data"]["counts"]["contacts"], 1)

    def test_customer_360_summary_counts_direct_and_indirect_open_tasks(self):
        customer = self.create_customer("SUMMARY_TASK_CUSTOMER", "任务汇总客户")
        direct_task = BusinessTask.objects.create(
            assignee_employee=self.employee,
            created_by_employee=self.employee,
            title="客户直接任务",
            due_at=timezone.now() + timedelta(days=1),
        )
        CustomerTaskLink.objects.create(
            customer_account=customer,
            business_task=direct_task,
        )
        communication = CustomerCommunication.objects.create(
            customer_account=customer,
            communication_type="EMAIL",
            direction="OUTBOUND",
            subject="任务来源沟通",
            content="用于验证客户汇总能统计间接来源任务。",
            occurred_at=timezone.now(),
            created_by_employee=self.employee,
        )
        indirect_task = BusinessTask.objects.create(
            assignee_employee=self.employee,
            created_by_employee=self.employee,
            title="沟通来源任务",
            due_at=timezone.now() - timedelta(hours=1),
        )
        CommunicationTaskLink.objects.create(
            communication=communication,
            business_task=indirect_task,
        )

        response = self.client.get(f"/api/v1/customers/{customer.pk}/summary/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["counts"]["open_tasks"], 2)
        self.assertEqual(response.data["data"]["counts"]["overdue_tasks"], 1)

    def test_collaborator_can_be_added_and_ended(self):
        customer = self.create_customer("COLLABORATOR_CUSTOMER", "协作客户")

        created = self.client.post(
            f"/api/v1/customers/{customer.pk}/collaborators/",
            {
                "employee_id": str(self.other_employee.pk),
                "reason": "共同跟进",
            },
            format="json",
        )
        ended = self.client.post(
            f"/api/v1/customers/{customer.pk}/collaborators/{self.other_employee.pk}/end/",
            {"reason": "协作结束"},
            format="json",
        )

        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(ended.status_code, 200, ended.data)
        self.assertIsNotNone(ended.data["data"]["effective_to"])

    def test_attention_change_closes_previous_effective_record(self):
        customer = self.create_customer("ATTENTION_CUSTOMER", "关注客户")
        key_account = ReferenceDictionary.objects.get(
            category_code="CUSTOMER_ATTENTION",
            item_code="KEY_ACCOUNT",
        )
        routine = ReferenceDictionary.objects.get(
            category_code="CUSTOMER_ATTENTION",
            item_code="ROUTINE",
        )

        first = self.client.post(
            f"/api/v1/customers/{customer.pk}/set-attention/",
            {"attention_level_item_id": str(key_account.pk), "reason": "重点机会"},
            format="json",
        )
        second = self.client.post(
            f"/api/v1/customers/{customer.pk}/set-attention/",
            {"attention_level_item_id": str(routine.pk), "reason": "转常规维护"},
            format="json",
        )

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 201, second.data)
        reviews = customer.attention_reviews.order_by("effective_from")
        self.assertEqual(reviews.count(), 2)
        self.assertIsNotNone(reviews.first().effective_to)
        self.assertIsNone(reviews.last().effective_to)

    def test_duplicate_effective_role_returns_validation_error(self):
        customer = self.create_customer("DUP_ROLE_CUSTOMER", "重复角色客户")
        entity = CustomerTransactionEntity.objects.create(
            customer_account=customer,
            entity_code="DUP_ROLE_ENTITY",
            legal_name="重复角色主体",
        )
        url = f"/api/v1/customer-entities/{entity.pk}/roles/"

        first = self.client.post(url, {"role_type": "CONTRACTING"}, format="json")
        duplicate = self.client.post(url, {"role_type": "CONTRACTING"}, format="json")

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(duplicate.status_code, 409, duplicate.data)
        self.assertEqual(duplicate.data["error"]["code"], "CONFLICT")

    def test_specific_contact_grant_allows_only_granted_customer(self):
        granted_customer = self.create_customer(
            "GRANTED_CUSTOMER",
            "授权客户",
            owner=self.other_employee,
        )
        denied_customer = self.create_customer(
            "DENIED_CUSTOMER",
            "未授权客户",
            owner=self.other_employee,
        )
        granted_contact = CustomerContact.objects.create(
            customer_account=granted_customer,
            display_name="授权联系人",
        )
        denied_contact = CustomerContact.objects.create(
            customer_account=denied_customer,
            display_name="未授权联系人",
        )
        permission = Permission.objects.get(
            content_type__app_label="customers",
            codename="view_customercontact",
        )
        CustomerDataAccessGrant.objects.create(
            employee=self.employee,
            customer_account=granted_customer,
            permission=permission,
            effective_from=timezone.now(),
            reason="测试精细数据授权",
        )

        granted = self.client.get(f"/api/v1/contacts/{granted_contact.pk}/")
        denied = self.client.get(f"/api/v1/contacts/{denied_contact.pk}/")

        self.assertEqual(granted.status_code, 200, granted.data)
        self.assertEqual(denied.status_code, 404)

    def test_action_permission_is_enforced_before_object_access(self):
        customer = self.create_customer("NO_CHANGE_CUSTOMER", "无修改权限客户")
        change_permission = Permission.objects.get(
            content_type__app_label="customers",
            codename="change_customeraccount",
        )
        self.user.user_permissions.remove(change_permission)
        if hasattr(self.user, "_perm_cache"):
            del self.user._perm_cache

        response = self.client.patch(
            f"/api/v1/customers/{customer.pk}/",
            {"account_name": "不应修改"},
            format="json",
            HTTP_IF_MATCH='"irrelevant"',
        )

        self.assertEqual(response.status_code, 403)
        customer.refresh_from_db()
        self.assertEqual(customer.account_name, "无修改权限客户")
