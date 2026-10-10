from django.test import TestCase

from apps.reference_data.models import ReferenceDictionary


class CustomerGradeDictionaryTests(TestCase):
    def test_customer_grade_definitions_match_business_rules(self):
        grades = list(
            ReferenceDictionary.objects.filter(
                category_code="CUSTOMER_GRADE",
                archived_at__isnull=True,
                status="ACTIVE",
            )
            .order_by("sort_order")
            .values_list("item_code", "display_name", "description")
        )

        self.assertEqual(
            grades,
            [
                ("A", "A", "非常优质"),
                ("B", "B", "优质"),
                ("C", "C", "良好"),
                ("D", "D", "一般"),
                ("E", "E", "较差"),
                ("F", "F（询价）", "恩特 ERP 历史询价等级；该值表示询价状态，不作为客户质量高低判断。"),
            ],
        )
