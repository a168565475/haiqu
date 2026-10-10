"""S8 默认只读预览，执行必须提供审核摘要和隔离数据库名。"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from apps.inventory.material_flow_reset import canonical, execute, preview


class Command(BaseCommand):
    help = '材料账重置清单；默认只读。S8 仅允许独立恢复库演练。'

    def add_arguments(self, parser):
        parser.add_argument('--output', required=True)
        parser.add_argument('--execute', action='store_true')
        parser.add_argument('--manifest')
        parser.add_argument('--approved-sha256')
        parser.add_argument('--target-database')
        parser.add_argument('--operator')
        parser.add_argument('--authorization')

    def handle(self, *args, **options):
        target = Path(options['output'])
        if target.exists():
            raise CommandError('输出文件已存在，禁止覆盖审核证据。')
        if options['execute']:
            if not all(options.get(key) for key in ['manifest', 'approved_sha256', 'target_database', 'operator']):
                raise CommandError('执行需要清单、已审核摘要和明确目标数据库。')
            try:
                manifest = json.loads(Path(options['manifest']).read_text(encoding='utf-8'))
                authorization = json.loads(Path(options['authorization']).read_text(encoding='utf-8')) if options['authorization'] else None
            except (OSError, ValueError) as error:
                raise CommandError(f'清单读取失败：{error}') from error
        elif any(options.get(key) for key in ['manifest','approved_sha256','target_database','operator','authorization']):
            raise CommandError('预览不接受执行参数。')
        # 先验证可写；执行成功后追加结果，中央审计仍是提交结果的权威记录。
        try:
            with target.open('x', encoding='utf-8') as output:
                result = execute(manifest, options['approved_sha256'], options['target_database'], operator=options['operator'], authorization=authorization) if options['execute'] else preview()
                output.write(canonical(result))
        except OSError as error:
            raise CommandError(f'证据写入失败，请根据中央审计核对是否已提交：{error}') from error
        self.stdout.write(self.style.SUCCESS(f"{'执行' if options['execute'] else '只读预览'}完成：{target}"))
