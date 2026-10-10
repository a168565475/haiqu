from django.core.management.base import BaseCommand

from apps.crm.models import CustomerCommunication
from apps.customers.models import CustomerAccount, CustomerActivityReview
from apps.customers.services import set_initial_activity_to_follow_up_from_imported_contact


SOURCE_SYSTEM = "ENTE_ERP"


class Command(BaseCommand):
    help = "按恩特源表已导入的最后联系时间，校正客户状态；默认只预览，使用 --apply 才会写入。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="确认写入客户状态")

    def handle(self, *args, **options):
        customer_ids = list(
            CustomerAccount.objects.filter(
                source_system=SOURCE_SYSTEM,
                archived_at__isnull=True,
            ).values_list("id", flat=True)
        )
        historical_contact_customer_ids = set(
            CustomerCommunication.objects.filter(
                source_system=SOURCE_SYSTEM,
                external_id__endswith=":LAST_CONTACT",
                customer_account_id__in=customer_ids,
            ).values_list("customer_account_id", flat=True)
        )
        current_reviews = {
            review.customer_account_id: review
            for review in CustomerActivityReview.objects.filter(
                customer_account_id__in=customer_ids,
                effective_to__isnull=True,
            )
        }
        candidate_ids = [
            customer_id
            for customer_id in historical_contact_customer_ids
            if (
                (review := current_reviews.get(customer_id)) is not None
                and review.activity_status == "INSUFFICIENT_DATA"
                and review.source_type == "SYSTEM"
                and review.formula_version == "initial-v1"
            )
        ]
        preserved_count = len(historical_contact_customer_ids) - len(candidate_ids)
        summary = (
            f"恩特客户 {len(customer_ids)} 条；已导入最后联系时间 "
            f"{len(historical_contact_customer_ids)} 条；待改为需跟进 {len(candidate_ids)} 条；"
            f"无最后联系时间 {len(customer_ids) - len(historical_contact_customer_ids)} 条；"
            f"保留现有非初始状态 {preserved_count} 条。"
        )
        if not options["apply"]:
            self.stdout.write(f"预览：{summary}")
            return

        updated_count = 0
        for customer in CustomerAccount.objects.filter(pk__in=candidate_ids).order_by("pk"):
            updated_count += int(
                set_initial_activity_to_follow_up_from_imported_contact(customer=customer)
                is not None
            )
        self.stdout.write(self.style.SUCCESS(f"已同步：{summary} 实际更新 {updated_count} 条。"))
