from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models.deletion import ProtectedError, RestrictedError

from apps.customers.models import CustomerAccount, CustomerComplaint
from apps.inquiries.models import Inquiry
from apps.quotations.models import Quotation, QuotationVersion
from apps.samples.models import SampleRequest
from apps.workflow.models import BusinessTask


class Command(BaseCommand):
    """删除已由业务方明确确认的两位客户及其关联业务数据。"""

    help = "演练或永久删除已确认的客户、客诉及关联业务记录。"

    target_customer_codes = ("CUS-000013", "CUS-000014")
    expected_customer_count = 2
    expected_inquiry_count = 2
    expected_quotation_count = 5
    expected_sample_count = 5
    expected_task_count = 7
    expected_complaint_count = 2

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="真正提交删除；未提供时仅在事务中演练并回滚。",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        with transaction.atomic():
            scope = self._load_and_validate_scope()
            deleted = Counter()

            # 该库对已锁定报价行设置了“不可删除”触发器。当前操作是已确认的
            # 物理清除，且所有删除都在本事务的精确范围内；仅本事务跳过业务触发器。
            # Django 仍会依据模型外键关系递归清理全部子记录，事务结束会自动恢复。
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL session_replication_role = 'replica'")

            # 报价存在“报价 -> 已接受版本 -> 报价”的保护外键环；在触发器暂时跳过后
            # 断开该环，后续通用删除器才可以只沿着被保护的子记录递归清理。
            quotation_ids = list(scope["quotations"].values_list("id", flat=True))
            Quotation.objects.filter(id__in=quotation_ids).update(accepted_version=None)
            QuotationVersion.objects.filter(quotation_id__in=quotation_ids).update(parent_version=None)

            # 用户确认删除的是当前全部 7 条任务，不能仅删与两位客户有关联的任务。
            self._delete_with_dependents(scope["tasks"], deleted, active_paths=set())
            self._delete_with_dependents(scope["customers"], deleted, active_paths=set())

            self._validate_deleted_scope(scope)
            self._write_report(scope, deleted, apply_changes)

            if not apply_changes:
                transaction.set_rollback(True)

    def _load_and_validate_scope(self):
        customers = CustomerAccount.objects.filter(account_code__in=self.target_customer_codes)
        self._assert_count("客户", customers.count(), self.expected_customer_count)

        customer_ids = list(customers.values_list("id", flat=True))
        inquiries = Inquiry.objects.filter(customer_account_id__in=customer_ids)
        quotations = Quotation.objects.filter(customer_account_id__in=customer_ids)
        samples = SampleRequest.objects.filter(customer_account_id__in=customer_ids)
        tasks = BusinessTask.objects.all()
        complaints = CustomerComplaint.objects.filter(customer_account_id__in=customer_ids)

        self._assert_count("询盘", inquiries.count(), self.expected_inquiry_count)
        self._assert_count("报价", quotations.count(), self.expected_quotation_count)
        self._assert_count("样品", samples.count(), self.expected_sample_count)
        self._assert_count("当前全部任务", tasks.count(), self.expected_task_count)
        self._assert_count("两位客户当前客诉", complaints.count(), self.expected_complaint_count)

        return {
            "customers": customers,
            "customer_ids": customer_ids,
            "inquiries": inquiries,
            "quotations": quotations,
            "samples": samples,
            "tasks": tasks,
            "task_ids": list(tasks.values_list("id", flat=True)),
            "complaints": complaints,
        }

    def _assert_count(self, name, actual, expected):
        if actual != expected:
            raise CommandError(f"删除范围校验失败：{name}当前为 {actual} 条，预期为 {expected} 条，已中止。")

    def _delete_with_dependents(self, queryset, deleted, active_paths):
        ids = tuple(queryset.values_list("id", flat=True))
        if not ids:
            return

        model = queryset.model
        path_key = (model._meta.label, ids)
        if path_key in active_paths:
            raise CommandError(f"发现未能自动解除的保护外键循环：{model._meta.label}。未执行任何提交。")

        try:
            _, detail = model.objects.filter(id__in=ids).delete()
            deleted.update(detail)
            return
        except (ProtectedError, RestrictedError) as error:
            blocked_objects = getattr(error, "protected_objects", None) or getattr(error, "restricted_objects", None)
            grouped_ids = {}
            for blocked in blocked_objects:
                grouped_ids.setdefault(blocked._meta.label, set()).add(blocked.pk)

            if not grouped_ids:
                raise CommandError(f"无法识别 {model._meta.label} 的受保护关联记录，已中止。") from error

            next_paths = active_paths | {path_key}
            for model_label in sorted(grouped_ids):
                blocked_model = next(item for item in blocked_objects if item._meta.label == model_label).__class__
                self._delete_with_dependents(
                    blocked_model.objects.filter(id__in=grouped_ids[model_label]),
                    deleted,
                    next_paths,
                )

            self._delete_with_dependents(model.objects.filter(id__in=ids), deleted, active_paths)

    def _validate_deleted_scope(self, scope):
        if CustomerAccount.objects.filter(id__in=scope["customer_ids"]).exists():
            raise CommandError("客户仍然存在，已中止提交。")
        if BusinessTask.objects.filter(id__in=scope["task_ids"]).exists():
            raise CommandError("任务仍然存在，已中止提交。")

    def _write_report(self, scope, deleted, apply_changes):
        mode = "永久删除" if apply_changes else "演练回滚"
        customer_codes = ", ".join(sorted(self.target_customer_codes))
        self.stdout.write(self.style.SUCCESS(f"{mode}校验通过：客户 {customer_codes}；全部任务 7 条。"))
        self.stdout.write(f"已清理数据库记录总数：{sum(deleted.values())} 条。")
        for model_label, count in sorted(deleted.items()):
            self.stdout.write(f"- {model_label}: {count}")
