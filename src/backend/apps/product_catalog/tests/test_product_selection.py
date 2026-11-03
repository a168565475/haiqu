from copy import deepcopy
from uuid import uuid4

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import models
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.organizations.models import Employee
from apps.reference_data.models import ProductionUnit

from ..models import ProductCatalog, ProductCatalogCategory, ProductCatalogColor, ProductCatalogName
from ..selection import resolve_product_selection


class ProductSelectionTests(TestCase):
    def setUp(self):
        self.category = ProductCatalogCategory.objects.create(name="选择测试类别")
        self.name = ProductCatalogName.objects.create(category=self.category, name="选择测试椅")
        self.unit, _ = ProductionUnit.objects.get_or_create(unit_name="套", defaults={"unit_code": "PC-SELECTION-SET"})
        self.product = ProductCatalog.objects.create(name=self.name, unit="套", item_number="A-1", specification="120",
                                                     materials=["铁"], thicknesses=["0.8"])
        self.color = ProductCatalogColor.objects.create(product=self.product, value="蓝色")

    def selection(self, **values):
        return {"catalog_version": self.product.updated_at.isoformat(), **values}

    def test_single_options_default_and_fixed_unit_identity(self):
        product, snapshot = resolve_product_selection(self.product.pk, self.selection())
        self.assertEqual(product.pk, self.product.pk)
        self.assertEqual(snapshot["unit_id"], str(self.unit.pk))
        self.assertEqual(snapshot["unit_code"], self.unit.unit_code)
        self.assertEqual(snapshot["color_id"], str(self.color.pk))
        self.assertEqual(snapshot["material"], "铁")
        self.assertEqual(snapshot["thickness"], "0.8")
        self.assertEqual(snapshot["version"], 1)
        self.assertEqual(snapshot["name_id"], str(self.name.pk))

    def test_unchanged_selection_preserves_archived_master_snapshot(self):
        _, snapshot = resolve_product_selection(self.product.pk, self.selection())
        before = deepcopy(snapshot)
        ProductCatalog.objects.filter(pk=self.product.pk).update(archived_at=timezone.now(), specification="新规格", materials=["铝"])
        ProductCatalogName.objects.filter(pk=self.name.pk).update(name="已改名")
        ProductionUnit.objects.filter(pk=self.unit.pk).update(status="INACTIVE")
        for catalog_id in (None, self.product.pk):
            _, saved = resolve_product_selection(catalog_id, None, existing_catalog_id=self.product.pk, existing_snapshot=snapshot)
            self.assertEqual(saved, before)
            self.assertIsNot(saved, snapshot)

    def test_multiple_options_require_explicit_choice(self):
        for field, changes in (("color_id", {"colors": True}), ("material", {"materials": ["铁", "铝"]}),
                               ("thickness", {"thicknesses": ["0.8", "1.0"]})):
            with self.subTest(field=field):
                if "colors" in changes:
                    extra = ProductCatalogColor.objects.create(product=self.product, value="黑色")
                else:
                    ProductCatalog.objects.filter(pk=self.product.pk).update(**changes)
                with self.assertRaises(ValidationError) as caught:
                    resolve_product_selection(self.product.pk, self.selection())
                self.assertIn(field, caught.exception.detail["product_selection"])
                if "colors" in changes:
                    extra.delete()
                else:
                    ProductCatalog.objects.filter(pk=self.product.pk).update(materials=["铁"], thicknesses=["0.8"])

    def test_foreign_color_and_invalid_material_or_thickness_rejected(self):
        other = ProductCatalog.objects.create(name=self.name, unit="套")
        other_color = ProductCatalogColor.objects.create(product=other, value="蓝色")
        for values in ({"color_id": str(other_color.pk)}, {"material": "木"}, {"thickness": "99"}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                resolve_product_selection(self.product.pk, self.selection(**values))

    def test_empty_option_lists_allow_empty_values(self):
        self.color.delete()
        ProductCatalog.objects.filter(pk=self.product.pk).update(materials=[], thicknesses=[])
        _, snapshot = resolve_product_selection(self.product.pk, self.selection())
        self.assertIsNone(snapshot["color_id"])
        self.assertEqual((snapshot["color_name"], snapshot["material"], snapshot["thickness"]), ("", "", ""))

    def test_inactive_or_missing_unit_rejected_on_new_selection(self):
        for unit in ("未定义单位", ""):
            ProductCatalog.objects.filter(pk=self.product.pk).update(unit=unit)
            with self.assertRaisesMessage(ValidationError, "唯一有效"):
                resolve_product_selection(self.product.pk, self.selection())
        ProductCatalog.objects.filter(pk=self.product.pk).update(unit="套")
        ProductionUnit.objects.filter(pk=self.unit.pk).update(status="INACTIVE")
        with self.assertRaisesMessage(ValidationError, "唯一有效"):
            resolve_product_selection(self.product.pk, self.selection())

    def test_invalid_or_missing_version_and_stale_version_rejected(self):
        for selection in ({}, {"catalog_version": "not-a-version"}, {"catalog_version": "2026-99-99"},
                          {"catalog_version": "2020-01-01T00:00:00+00:00"}):
            with self.subTest(selection=selection), self.assertRaises(ValidationError):
                resolve_product_selection(self.product.pk, selection)

    def test_archived_product_name_or_category_and_bad_id_rejected(self):
        for instance in (self.product, self.name, self.category):
            type(instance).objects.filter(pk=instance.pk).update(archived_at=timezone.now())
            with self.assertRaises(ValidationError):
                resolve_product_selection(self.product.pk, self.selection())
            type(instance).objects.filter(pk=instance.pk).update(archived_at=None)
        for catalog_id in (None, uuid4(), "bad-id"):
            with self.subTest(catalog_id=catalog_id), self.assertRaises(ValidationError):
                resolve_product_selection(catalog_id, self.selection())

    def test_all_consumers_protect_catalog_and_reject_two_sources(self):
        for app, name in (("inquiries", "InquiryItem"), ("quotations", "QuotationLine"), ("samples", "SampleProduct"),
                          ("sales_orders", "SalesOrderLine"), ("production_tasks", "ProductionTaskProduct"), ("boms", "Bom")):
            with self.subTest(model=name):
                model = apps.get_model(app, name)
                self.assertIs(model._meta.get_field("product_catalog").remote_field.on_delete, models.PROTECT)
                instance = model(product_id=uuid4(), product_catalog=self.product)
                constraint = next(row for row in model._meta.constraints if row.name.endswith("product_source_exclusive"))
                with self.assertRaises(ModelValidationError):
                    constraint.validate(model, instance)
                instance.product_id = None
                constraint.validate(model, instance)
                self.assertEqual(instance.product_selection_snapshot, {})


@override_settings(SALES_ACCESS_ENABLED=False, MODULE_ACCESS_ENABLED=False)
class ProductSelectionOptionsTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="product_consumer", password="SelectionTest123!")
        self.employee = Employee.objects.create(user=self.user, employee_code="PRODUCT_CONSUMER", display_name="产品使用人")
        self.client.force_login(self.user)
        self.category = ProductCatalogCategory.objects.create(name="消费选项类别")
        self.name = ProductCatalogName.objects.create(category=self.category, name="消费选项品名")
        self.product = ProductCatalog.objects.create(name=self.name, unit="套", materials=["铁"], thicknesses=["0.8"])
        self.unit, _ = ProductionUnit.objects.get_or_create(unit_name="套", defaults={"unit_code": "PC-OPTIONS-SET"})
        self.url = "/api/v1/product-catalog/selection-options/"

    def grant(self, code):
        app_label, codename = code.split(".")
        self.user.user_permissions.set([Permission.objects.get(content_type__app_label=app_label, codename=codename)])

    def test_each_consumer_view_grant_can_read_without_catalog_permission(self):
        for code in ("product_catalog.view_productcatalog", "inquiries.view_inquiry", "quotations.view_quotation",
                     "samples.view_samplerequest", "sales_orders.view_salesorder", "production_tasks.view_productiontask", "boms.view_bom"):
            with self.subTest(permission=code):
                self.grant(code)
                response = self.client.get(self.url)
                self.assertEqual(response.status_code, 200, response.data)
                product = response.data["data"]["products"][0]
                self.assertEqual(product["unit_id"], str(self.unit.pk))
                self.assertEqual(product["catalog_version"], product["updated_at"])
                self.assertEqual(product["materials"], ["铁"])

    def test_missing_grant_employee_and_session_denied(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.grant("boms.view_bom")
        self.employee.archived_at = timezone.now()
        self.employee.save(update_fields=["archived_at"])
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.client.logout()
        self.assertIn(self.client.get(self.url).status_code, (401, 403))

    def test_only_active_records_and_colors_are_listed(self):
        self.grant("boms.view_bom")
        ProductCatalogColor.objects.create(product=self.product, value="可用蓝")
        ProductCatalogColor.objects.create(product=self.product, value="停用蓝", archived_at=timezone.now())
        archived_name = ProductCatalogName.objects.create(category=self.category, name="停用品名", archived_at=timezone.now())
        ProductCatalog.objects.create(name=archived_name)
        ProductCatalog.objects.create(name=self.name, archived_at=timezone.now())
        response = self.client.get(self.url)
        self.assertEqual([row["id"] for row in response.data["data"]["products"]], [str(self.product.pk)])
        self.assertEqual([row["name"] for row in response.data["data"]["names"]], [self.name.name])
        self.assertEqual([row["value"] for row in response.data["data"]["products"][0]["colors"]], ["可用蓝"])
        self.assertEqual(self.client.post(self.url, {}, format="json").status_code, 405)
