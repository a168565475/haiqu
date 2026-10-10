import hashlib
import json
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.boms.models import Bom
from apps.core.audit import write_audit_log
from apps.inventory.models import FinishedGoodsReceipt, MaterialInboundLine
from apps.organizations.models import Employee, EmployeeStatus
from apps.procurement.models import PurchaseOrder, PurchaseRequest
from apps.production_tasks.models import ProductionTask
from apps.production_tasks.numbering import lock_production_task_number_year


CONFIRM_TOKEN = "RENUMBER-PRODUCTION-TASKS"


class Command(BaseCommand):
    help = "把指定年份的生产任务单统一重排为 HT + 两位年份 + 三位流水，并同步下游快照。默认仅预检。"

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=timezone.localdate().year)
        parser.add_argument("--current-sequence", type=int, required=True, help="重排后最新一张任务单的三位流水。")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--confirm", help=f"写入时必须传入 {CONFIRM_TOKEN}。")
        parser.add_argument("--actor-employee-code", help="执行编号重排的超级管理员员工编号。")
        parser.add_argument("--expected-task-count", type=int, help="写入前必须与预检任务数完全一致。")
        parser.add_argument("--expected-old-number-sha256", help="写入前必须与预检摘要完全一致。")
        parser.add_argument("--report", help="将新旧编号映射及同步结果写入 JSON。")

    def handle(self, *args, **options):
        year = options["year"]
        current_sequence = options["current_sequence"]
        if year < 2000 or year > 2099:
            raise CommandError("年份必须在 2000 至 2099 之间。")
        if current_sequence < 1 or current_sequence > 999:
            raise CommandError("当前流水必须在 001 至 999 之间。")

        tasks, mapping, target_numbers, source_digest = self._plan(year, current_sequence)
        changed_count = sum(item["old_number"] != item["new_number"] for item in mapping)
        if not options["commit"]:
            self.stdout.write(self.style.SUCCESS(
                f"预检通过：{year} 年 {len(tasks)} 张任务单将按创建先后映射为 "
                f"{target_numbers[0]}～{target_numbers[-1]}，需修改 {changed_count} 张。"
            ))
            self.stdout.write(f"任务数：{len(tasks)}")
            self.stdout.write(f"旧编号摘要 SHA-256：{source_digest}")
            self.stdout.write(f"写入请追加 --commit --confirm {CONFIRM_TOKEN}。")
            return
        if options.get("confirm") != CONFIRM_TOKEN:
            raise CommandError(f"请明确追加 --confirm {CONFIRM_TOKEN} 后再写入。")
        if options.get("expected_task_count") != len(tasks):
            raise CommandError("--expected-task-count 与当前预检任务数不一致，禁止写入。")
        if options.get("expected_old_number_sha256") != source_digest:
            raise CommandError("--expected-old-number-sha256 与当前预检摘要不一致，禁止写入。")
        actor_code = str(options.get("actor_employee_code") or "").strip()
        if not actor_code:
            raise CommandError("写入必须明确传入 --actor-employee-code。")

        actor = self._actor(actor_code)
        sync_counts = {"purchase_orders": 0, "finished_goods_receipts": 0, "material_inbound_lines": 0}
        audit_count = 0
        with transaction.atomic():
            lock_production_task_number_year(date(year, 1, 1))
            tasks, mapping, target_numbers, locked_digest = self._plan(
                year,
                current_sequence,
                lock_rows=True,
            )
            if len(tasks) != options["expected_task_count"] or locked_digest != source_digest:
                raise CommandError("任务单在预检后发生变化，本次事务已回滚。")
            locked_tasks = {str(task.pk): task for task in tasks}

            now = timezone.now()
            for item in mapping:
                task = locked_tasks[item["task_id"]]
                if item["old_number"] == item["new_number"]:
                    continue
                task.task_number = f"TMP-{task.pk.hex.upper()}"
                task.updated_at = now
                task.save(update_fields=["task_number", "updated_at"])

            for item in mapping:
                task = locked_tasks[item["task_id"]]
                old_number = item["old_number"]
                new_number = item["new_number"]
                if old_number != new_number:
                    task.task_number = new_number
                    task.updated_at = now
                    task.save(update_fields=["task_number", "updated_at"])
                    write_audit_log(
                        object_type="PRODUCTION_TASK",
                        object_id=task.pk,
                        context_type="CUSTOMER_ACCOUNT",
                        context_id=task.customer_account_id,
                        action="TASK_NUMBER_RENUMBERED",
                        actor_employee=actor,
                        before_data={"task_number": old_number},
                        after_data={"task_number": new_number},
                    )
                    audit_count += 1
                sync_counts["purchase_orders"] += PurchaseOrder.objects.filter(
                    production_task=task
                ).exclude(production_task_number_snapshot=new_number).update(
                    production_task_number_snapshot=new_number,
                    updated_at=now,
                )
                sync_counts["finished_goods_receipts"] += FinishedGoodsReceipt.objects.filter(
                    production_task_product__production_task=task
                ).filter(
                    ~Q(task_number_snapshot=new_number) | ~Q(source_document_number=new_number)
                ).update(
                    task_number_snapshot=new_number,
                    source_document_number=new_number,
                    updated_at=now,
                )
                sync_counts["material_inbound_lines"] += MaterialInboundLine.objects.filter(
                    purchase_order_line__purchase_order__production_task=task
                ).exclude(production_task_number_snapshot=new_number).update(
                    production_task_number_snapshot=new_number,
                    updated_at=now,
                )

            checks = self._checks(year, target_numbers)
            if not all(checks.values()):
                raise CommandError("编号或下游快照验收失败，本次事务已回滚。")

        report = {
            "generated_at": timezone.now().isoformat(),
            "year": year,
            "current_sequence": current_sequence,
            "task_count": len(tasks),
            "changed_count": changed_count,
            "source_digest_sha256": source_digest,
            "actor_employee_code": actor.employee_code,
            "audit_count": audit_count,
            "range": {"first": target_numbers[0], "last": target_numbers[-1]},
            "sync_counts": sync_counts,
            "dynamic_links": {
                "boms": Bom.objects.filter(production_task__order_date__year=year).count(),
                "purchase_requests": PurchaseRequest.objects.filter(production_task__order_date__year=year).count(),
            },
            "checks": checks,
            "mapping": mapping,
            "audit_note": "历史审计日志保持不可变；本次为每张变更任务新增 TASK_NUMBER_RENUMBERED 记录。",
        }
        self._write_report(options.get("report"), report)
        self.stdout.write(self.style.SUCCESS(
            f"编号重排完成：{target_numbers[0]}～{target_numbers[-1]}；"
            f"采购单快照 {sync_counts['purchase_orders']} 条、材料入库快照 {sync_counts['material_inbound_lines']} 条。"
        ))

    def _plan(self, year, current_sequence, *, lock_rows=False):
        queryset = ProductionTask.objects.filter(order_date__year=year).select_related(
            "customer_account"
        ).order_by("created_at", "id")
        if lock_rows:
            queryset = queryset.select_for_update()
        tasks = list(queryset)
        if not tasks:
            raise CommandError(f"{year} 年没有生产任务单。")
        first_sequence = current_sequence - len(tasks) + 1
        if first_sequence < 1:
            raise CommandError(
                f"{year} 年共有 {len(tasks)} 张任务单，无法在当前流水 {current_sequence:03d} 前完整排入。"
            )
        mapping = [
            {
                "task_id": str(task.pk),
                "old_number": task.task_number,
                "new_number": f"HT{year % 100:02d}{first_sequence + index:03d}",
                "order_date": task.order_date.isoformat(),
                "created_at": task.created_at.isoformat(),
            }
            for index, task in enumerate(tasks)
        ]
        target_numbers = [item["new_number"] for item in mapping]
        collisions = list(
            ProductionTask.objects.filter(task_number__in=target_numbers)
            .exclude(pk__in=[task.pk for task in tasks])
            .values_list("task_number", flat=True)
        )
        if collisions:
            raise CommandError(f"目标编号已被其他年份占用：{'、'.join(sorted(collisions))}")
        digest_payload = "\n".join(
            f"{item['task_id']}|{item['old_number']}|{item['new_number']}"
            for item in mapping
        )
        source_digest = hashlib.sha256(digest_payload.encode("utf-8")).hexdigest().upper()
        return tasks, mapping, target_numbers, source_digest

    def _checks(self, year, target_numbers):
        tasks = ProductionTask.objects.filter(order_date__year=year)
        return {
            "all_task_numbers_match_mapping": set(tasks.values_list("task_number", flat=True)) == set(target_numbers),
            "all_task_numbers_match_format": all(
                len(number) == 7 and number.startswith(f"HT{year % 100:02d}") and number[4:].isdigit()
                for number in tasks.values_list("task_number", flat=True)
            ),
            "bom_links_intact": not Bom.objects.filter(
                production_task__order_date__year=year,
            ).exclude(production_task__task_number__in=target_numbers).exists(),
            "purchase_order_snapshots_match": not PurchaseOrder.objects.filter(
                production_task__order_date__year=year,
            ).exclude(production_task_number_snapshot=F("production_task__task_number")).exists(),
            "finished_goods_snapshots_match": not FinishedGoodsReceipt.objects.filter(
                production_task_product__production_task__order_date__year=year,
            ).filter(
                ~Q(task_number_snapshot=F("production_task_product__production_task__task_number"))
                | ~Q(source_document_number=F("production_task_product__production_task__task_number"))
            ).exists(),
            "material_inbound_snapshots_match": not MaterialInboundLine.objects.filter(
                purchase_order_line__purchase_order__production_task__order_date__year=year,
            ).exclude(
                production_task_number_snapshot=F(
                    "purchase_order_line__purchase_order__production_task__task_number"
                )
            ).exists(),
        }

    def _actor(self, employee_code):
        actor = Employee.objects.filter(
            employee_code=employee_code,
            status=EmployeeStatus.ACTIVE,
            archived_at__isnull=True,
            user__is_superuser=True,
            user__is_active=True,
        ).select_related("user").first()
        if actor is None:
            raise CommandError("指定员工不存在、已停用，或不是有效超级管理员。")
        return actor

    def _write_report(self, report_path, report):
        if not report_path:
            return
        path = Path(report_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(f"验收报告：{path}")
