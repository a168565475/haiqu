from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models.deletion import ProtectedError, RestrictedError

from apps.customers.models import CustomerAccount, CustomerContact


class Command(BaseCommand):
    """演练或清空当前全部恩特导入客户，供确认后的重新导入使用。"""

    help = "清空恩特 ERP 导入的全部客户、联系人和关联客户资料；默认仅演练并回滚。"

    source_system = "ENTE_ERP"
    expected_customer_count = 63
    expected_contact_count = 66

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="真正提交删除；默认只演练并回滚。")

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        with transaction.atomic():
            customers = CustomerAccount.objects.filter(source_system=self.source_system)
            self._assert_count("恩特客户", customers.count(), self.expected_customer_count)
            self._assert_count("系统全部客户", CustomerAccount.objects.count(), self.expected_customer_count)

            contacts = CustomerContact.objects.filter(customer_account__source_system=self.source_system)
            self._assert_count("恩特联系人", contacts.count(), self.expected_contact_count)
            self._assert_count("系统全部联系人", CustomerContact.objects.count(), self.expected_contact_count)

            # 已确认的物理清空仅作用于本事务。跳过锁定报价等业务触发器，
            # Django 仍会按外键关系递归删除被客户记录保护的全部子记录。
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL session_replication_role = 'replica'")

            deleted = Counter()
            self._delete_with_dependents(customers, deleted, active_paths=set())

            if CustomerAccount.objects.exists() or CustomerContact.objects.exists():
                raise CommandError("客户或联系人仍然存在，已中止提交。")

            mode = "永久清空" if apply_changes else "演练回滚"
            self.stdout.write(self.style.SUCCESS(f"{mode}校验通过：63 个客户、66 个联系人。"))
            self.stdout.write(f"已清理数据库记录总数：{sum(deleted.values())} 条。")
            for model_label, count in sorted(deleted.items()):
                self.stdout.write(f"- {model_label}: {count}")

            if not apply_changes:
                transaction.set_rollback(True)

    def _assert_count(self, name, actual, expected):
        if actual != expected:
            raise CommandError(f"清空范围校验失败：{name}当前为 {actual} 条，预期为 {expected} 条，已中止。")

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
            model_by_label = {}
            for blocked in blocked_objects:
                model_by_label[blocked._meta.label] = blocked.__class__
                grouped_ids.setdefault(blocked._meta.label, set()).add(blocked.pk)
            if not grouped_ids:
                raise CommandError(f"无法识别 {model._meta.label} 的受保护关联记录，已中止。") from error

            next_paths = active_paths | {path_key}
            for model_label in sorted(grouped_ids):
                self._delete_with_dependents(
                    model_by_label[model_label].objects.filter(id__in=grouped_ids[model_label]),
                    deleted,
                    next_paths,
                )
            self._delete_with_dependents(model.objects.filter(id__in=ids), deleted, active_paths)
