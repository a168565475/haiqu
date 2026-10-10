from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.organizations.models import RoleProfile
from apps.access_control.services import create_role

INITIAL_ROLES = (
    ("GENERAL_MANAGER", "总经理"), ("FACTORY_MANAGER", "厂长"), ("PURCHASING", "采购"),
    ("METAL_DIRECTOR", "金工主任"), ("ASSEMBLY_DIRECTOR", "装配主任"), ("SEWING_DIRECTOR", "车缝主任"),
    ("WAREHOUSE_KEEPER", "仓管"), ("MERCHANDISER", "跟单"), ("QUALITY", "品质"), ("FINANCE", "财务"),
    ("OUTSOURCING", "外协"), ("PMC", "PMC"), ("ADMINISTRATION", "行政"), ("TECHNICAL", "技术"),
    ("COATING_MATERIALS", "喷塑收发料"), ("METAL_SAMPLING", "金工打样"), ("FABRIC_SAMPLING", "布面打样"),
    ("CASHIER", "出纳"), ("SALESPERSON", "业务员"), ("ACCOUNT_MANAGER", "客户经理"),
)


class Command(BaseCommand):
    help = "预览 20 个空角色初始化；只有显式 --apply 才写入，不变更现有授权或员工。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        # Serializes concurrent initialization without changing existing business rows.
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(20260928, 2)")
        pending = []
        for code, name in INITIAL_ROLES:
            existing = RoleProfile.objects.filter(role_code=code).first()
            if existing:
                if existing.display_name != name:
                    raise CommandError(f"编码 {code} 已被其他角色名称使用；未写入。")
                self.stdout.write(f"保留 {code} {name}（不更改权限、成员或状态）")
            elif RoleProfile.objects.filter(display_name=name).exists() or Group.objects.filter(name=f"ERP_ROLE:{code}").exists():
                raise CommandError(f"{code} / {name} 存在名称或权限组冲突；未写入。")
            else:
                pending.append((code, name))
                self.stdout.write(f"待创建空角色 {code} {name}")
        if not options["apply"]:
            self.stdout.write(f"仅预览：缺少 {len(pending)} 个角色。")
            return
        user = get_user_model().objects.filter(username="admin", is_superuser=True, is_active=True).first()
        if user is None:
            raise CommandError("没有有效的 admin 超级管理员。")
        request = SimpleNamespace(user=user, META={}, headers={})
        for code, name in pending:
            create_role(request, {"role_code": code, "display_name": name, "description": ""})
        self.stdout.write(self.style.SUCCESS(f"新增 {len(pending)} 个空角色；现有角色与员工保持原状。"))
