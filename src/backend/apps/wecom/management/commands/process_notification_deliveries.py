import json
from collections import Counter
from datetime import timedelta
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.wecom.models import NotificationDelivery
from apps.wecom.notification_services import process_delivery, recover_abandoned_deliveries


class Command(BaseCommand):
    help = "预览已持久化的企业微信通知；仅 --execute 执行投递或回收。不会创建业务事件。"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50, help="最多检查的投递记录数，范围 1..500。")
        parser.add_argument("--execute", action="store_true", help="执行发送或回收；省略时只读预览。")
        parser.add_argument("--delivery-id", type=UUID, action="append", default=[],
                            help="限定投递记录 UUID，可重复指定。重试必须明确指定记录。")
        parser.add_argument("--retry-failed", action="store_true",
                            help="允许重试指定 ID 的 FAILED 记录；必须配合 --delivery-id。")
        parser.add_argument("--retry-uncertain", action="store_true",
                            help="核对后允许重试指定 ID 的 UNCERTAIN 记录，可能重复送达；必须配合 --delivery-id。")
        parser.add_argument("--recover-processing", action="store_true",
                            help="回收全队列超过五分钟的 PROCESSING 为 UNCERTAIN；本次不会自动重发这些记录。")

    def handle(self, *args, **options):
        limit = options["limit"]
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
            raise CommandError("--limit 必须为 1..500 的整数。")
        try:
            delivery_ids = list(dict.fromkeys(UUID(str(value)) for value in options["delivery_id"]))
        except (TypeError, ValueError):
            raise CommandError("--delivery-id 必须是有效 UUID。") from None
        if (options["retry_failed"] or options["retry_uncertain"]) and not delivery_ids:
            raise CommandError("重试 FAILED / UNCERTAIN 必须通过 --delivery-id 明确指定记录，禁止全队列重试。")
        if len(delivery_ids) > limit:
            raise CommandError("指定的不同投递 ID 数量超过 --limit，请减少 ID 或明确提高限制。")

        statuses = [NotificationDelivery.Status.PENDING]
        if options["retry_failed"]:
            statuses.append(NotificationDelivery.Status.FAILED)
        if options["retry_uncertain"]:
            statuses.append(NotificationDelivery.Status.UNCERTAIN)
        candidates = NotificationDelivery.objects.filter(
            channel=NotificationDelivery.Channel.WECOM, status__in=statuses,
        ).order_by("created_at", "pk")
        if delivery_ids:
            candidates = candidates.filter(pk__in=delivery_ids)
            eligible_ids = set(candidates.values_list("pk", flat=True))
            rejected = [str(value) for value in delivery_ids if value not in eligible_ids]
            if rejected:
                raise CommandError("以下投递不存在、不是企微渠道或状态不匹配，未执行任何操作：" + ", ".join(rejected))

        # 回收前固定候选集合，禁止把本次回收成 UNCERTAIN 的记录顺带重发。
        candidate_count = candidates.count()
        rows = list(candidates[:limit])
        recoverable = 0
        if options["recover_processing"]:
            recoverable = NotificationDelivery.objects.filter(
                channel=NotificationDelivery.Channel.WECOM,
                status=NotificationDelivery.Status.PROCESSING,
                last_attempt_at__lt=timezone.now() - timedelta(minutes=5),
            ).count()

        summary = {
            "mode": "execute" if options["execute"] else "dry-run",
            "candidate_count": candidate_count,
            "selected_count": len(rows),
            "selected": [{"id": str(row.pk), "status": row.status} for row in rows],
            "recover_scope": "all_wecom_processing_older_than_5_minutes" if options["recover_processing"] else "none",
            "recoverable_count": recoverable,
            "recovered_count": 0,
            "checked_count": 0,
            "result_status_counts": {},
            "execution_finished": False,
        }
        if not options["execute"]:
            self.stdout.write("DRY-RUN：只读预览，未发送消息、未回收记录。使用 --execute 才执行。")
            self.stdout.write(json.dumps(summary, ensure_ascii=False))
            return

        results = Counter()
        try:
            if options["recover_processing"]:
                summary["recovered_count"] = recover_abandoned_deliveries()
            for row in rows:
                result = process_delivery(
                    row,
                    allow_uncertain=options["retry_uncertain"] and row.status == NotificationDelivery.Status.UNCERTAIN,
                    allow_failed=options["retry_failed"] and row.status == NotificationDelivery.Status.FAILED,
                )
                results[result.status] += 1
                summary["checked_count"] += 1
            summary["execution_finished"] = True
        finally:
            # 异常继续向上抛出，同时保留已经完成的检查数量，避免报告整批成功。
            summary["result_status_counts"] = dict(results)
            self.stdout.write(json.dumps(summary, ensure_ascii=False))
            self.stdout.write("状态统计为各记录执行后返回状态；ACCEPTED 仅代表企微受理，不代表送达或已读。UNCERTAIN 须先核对，禁止盲目重发。")
        if any(status != NotificationDelivery.Status.ACCEPTED for status in results):
            raise CommandError("本次检查仍有未受理或待核对的投递，详情见 result_status_counts；未自动再次重试。")
