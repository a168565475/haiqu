from django.core.management.base import BaseCommand

from apps.boms.image_files import purge_expired_bom_line_image_drafts


class Command(BaseCommand):
    help = "清理已过期且尚未绑定到裁剪明细的 BOM 草稿图片。"

    def handle(self, *args, **options):
        total = 0
        while True:
            deleted = purge_expired_bom_line_image_drafts(limit=500)
            total += deleted
            if deleted < 500:
                break
        self.stdout.write(self.style.SUCCESS(f"已清理 {total} 张过期 BOM 草稿图片。"))
