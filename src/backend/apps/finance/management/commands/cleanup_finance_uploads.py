from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from apps.files.models import BusinessFile
from apps.organizations.models import Employee
from apps.finance.receipt_models import FinanceReceiptUpload
from apps.finance.receipt_uploads import compensate_upload_file, discard_receipt_upload, file_has_other_references, read_recovery_record, receipt_file_path


class Command(BaseCommand):
    help = "预检指定财务水单；仅 --apply 清理确切未绑定项，不按年龄或目录批删。"

    def add_arguments(self, parser):
        parser.add_argument("--ids", nargs="+", type=UUID, default=[])
        parser.add_argument("--orphan-file-ids", nargs="+", type=UUID, default=[])
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if not options["ids"] and not options["orphan_file_ids"]:
            raise CommandError("必须提供确切 --ids 或有 REGISTERED 审计的 --orphan-file-ids。")
        failures = []
        for upload_id in dict.fromkeys(options["ids"]):
            upload = FinanceReceiptUpload.objects.select_related("file", "owner_employee").filter(pk=upload_id).first()
            if upload is None:
                failures.append(f"{upload_id}: NOT_FOUND")
                continue
            referenced = file_has_other_references(upload.file, own_upload_id=upload.pk)
            self.stdout.write(f"upload={upload.pk} owner={upload.owner_employee_id} statement={upload.statement_id} "
                f"status={upload.status} referenced={referenced} exists={receipt_file_path(upload.file).is_file()}")
            if options["apply"]:
                if referenced or upload.status == "BOUND":
                    failures.append(f"{upload_id}: REFERENCED_RECORD")
                    continue
                # 服务再次加锁检查，DISCARD_PENDING 是之前同一确切清理的可重试状态。
                discard_receipt_upload(upload.pk, actor=upload.owner_employee)
                self.stdout.write(f"upload={upload.pk} DISCARDED exists={receipt_file_path(upload.file).is_file()}")
        for file_id in dict.fromkeys(options["orphan_file_ids"]):
            file = BusinessFile.objects.select_related("uploaded_by_employee").filter(pk=file_id).first()
            if file is None:
                record = read_recovery_record(file_id)
                owner = Employee.objects.filter(pk=record["owner_id"]).first()
                if owner is None:
                    failures.append(f"{file_id}: UNKNOWN_OWNER")
                    continue
                self.stdout.write(f"orphan_file={file_id} owner={owner.pk} metadata=MISSING recovery=PRESENT")
                if options["apply"]:
                    compensate_upload_file(file_id, actor=owner)
                    self.stdout.write(f"orphan_file={file_id} RECOVERY_CLEARED")
                continue
            self.stdout.write(f"orphan_file={file.pk} owner={file.uploaded_by_employee_id} exists={receipt_file_path(file).is_file()}")
            if options["apply"]:
                if file.uploaded_by_employee is None:
                    failures.append(f"{file_id}: UNKNOWN_OWNER")
                    continue
                compensate_upload_file(file.pk, actor=file.uploaded_by_employee)
                self.stdout.write(f"orphan_file={file_id} COMPENSATED")
        if failures:
            raise CommandError("; ".join(failures))
