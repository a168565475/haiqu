"""专项授权后通过Django shell执行；只创建/清理本任务登记的QA资源。"""
import json
import os
import secrets
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.db import transaction

from apps.core.audit import write_audit_log
from apps.organizations.models import Employee
from apps.product_catalog.models import ProductCatalog, ProductCatalogColor, ProductCatalogName


TASK = "2ebd7b22"
PREFIX = "QA_PRODUCT_20261016_2ebd7b22"
DIRECTORY = Path("/app/.tmp/product-catalog-20261016-2ebd7b22")
ACCOUNTS = DIRECTORY / "accounts.json"
CREATED = DIRECTORY / "created-records.json"
if os.environ.get("QA_ALLOW_REAL_DB_WRITE") != "I_UNDERSTAND":
    raise RuntimeError("缺少本任务真实写库授权标志")
action = os.environ.get("PRODUCT_CATALOG_QA_ACTION")
User = get_user_model()

if action == "create":
    if ACCOUNTS.exists():
        raise RuntimeError("已有资源清单，拒绝覆盖")
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    accounts = {"task": TASK, "accounts": []}
    permission = Permission.objects.get(content_type__app_label="product_catalog", codename="view_productcatalog")
    with transaction.atomic():
        for mode in ["read", "none"]:
            username = f"qa_product_{mode}_{TASK}"
            code = f"QA_PC_{mode.upper()}_{TASK.upper()}"
            if User.objects.filter(username=username).exists() or Employee.objects.filter(employee_code=code).exists():
                raise RuntimeError("账号或员工编号已存在，拒绝接管")
            password = secrets.token_urlsafe(30)
            user = User.objects.create_user(username=username, password=password)
            employee = Employee.objects.create(user=user, employee_code=code, display_name=f"产品管理专项QA-{mode}")
            if mode == "read":
                user.user_permissions.add(permission)
            accounts["accounts"].append({"mode": mode, "user_id": user.pk, "employee_id": str(employee.pk), "username": username, "employee_code": code, "password": password})
        # 文件写入失败会使上述事务回滚；凭据仅留在已登记临时范围，不打印。
        ACCOUNTS.write_text(json.dumps(accounts), encoding="utf-8")
    print(json.dumps({"action": action, "created_accounts": 2, "manifest": str(ACCOUNTS)}))
elif action == "cleanup":
    from django.utils.dateparse import parse_datetime

    if not CREATED.exists() or not ACCOUNTS.exists():
        raise RuntimeError("缺少本任务资源清单，不能确认归属，停止清理")
    manifest = json.loads(CREATED.read_text(encoding="utf-8"))
    accounts = json.loads(ACCOUNTS.read_text(encoding="utf-8"))
    if manifest["task"] != TASK or accounts["task"] != TASK:
        raise RuntimeError("资源清单所属任务不符")
    name_ids, product_ids = manifest["name_ids"], manifest["product_ids"]
    expected_names, expected_products = manifest.get("expected_names", {}), manifest.get("expected_products", {})
    if (len(name_ids) != len(set(name_ids)) or len(product_ids) != len(set(product_ids))
            or set(expected_names) != set(name_ids) or set(expected_products) != set(product_ids)):
        raise RuntimeError("资源ID或最后成功写入快照不完整，停止清理")
    if len(accounts["accounts"]) != 2 or {item["mode"] for item in accounts["accounts"]} != {"read", "none"}:
        raise RuntimeError("账号清单不完整，停止清理")
    for account in accounts["accounts"]:
        mode = account["mode"]
        if account["username"] != f"qa_product_{mode}_{TASK}" or account["employee_code"] != f"QA_PC_{mode.upper()}_{TASK.upper()}":
            raise RuntimeError("账号或员工编号不属于本任务，停止清理")
    with transaction.atomic():
        names = list(ProductCatalogName.objects.select_for_update().filter(pk__in=name_ids).order_by("pk"))
        if {str(name.pk) for name in names} != set(name_ids) or any(not name.name.startswith(PREFIX) for name in names):
            raise RuntimeError("品名ID或所属标记不一致，停止清理")
        for name in names:
            expected = expected_names[str(name.pk)]
            # 新建子产品会刷新品名时间戳；仅核对原名、类别、状态和完整子产品集合。
            if name.archived_at is not None or name.name != expected.get("name") or str(name.category_id) != expected.get("category_id"):
                raise RuntimeError("品名或类别被外部修改，停止清理")
        products = list(ProductCatalog.objects.select_for_update().filter(name_id__in=name_ids).order_by("pk"))
        if {str(product.pk) for product in products} != set(product_ids) or any(product.source_sha256 or product.source_import_id for product in products):
            raise RuntimeError("产品清单变化或包含来源产品，停止清理")
        colors = list(ProductCatalogColor.objects.select_for_update().filter(product_id__in=product_ids).order_by("pk"))
        fields = {"product_code", "item_number", "specification", "unit", "scale"}
        for product in products:
            expected = expected_products[str(product.pk)]
            timestamp = expected.get("updated_at")
            try:
                expected_time = parse_datetime(timestamp) if isinstance(timestamp, str) else None
            except ValueError as exc:
                raise RuntimeError("产品快照时间戳无效，停止清理") from exc
            if expected_time is None or product.updated_at != expected_time or product.archived_at is not None:
                raise RuntimeError("产品版本或归档状态变化，停止清理")
            if str(product.name_id) != expected.get("name_id") or expected.get("fields") != {key: getattr(product, key) for key in fields}:
                raise RuntimeError("产品所属品名或业务字段变化，停止清理")
            product_colors = [color for color in colors if color.product_id == product.pk]
            known_color_ids = expected.get("color_ids", [])
            active_colors = expected.get("colors", [])
            if len(known_color_ids) != len(set(known_color_ids)) or {str(color.pk) for color in product_colors} != set(known_color_ids):
                raise RuntimeError("存在未登记或缺失的颜色ID，停止清理")
            expected_active = {color["id"]: color["value"] for color in active_colors}
            if len(expected_active) != len(active_colors) or expected_active != {str(color.pk): color.value for color in product_colors if color.archived_at is None}:
                raise RuntimeError("颜色值或归档状态变化，停止清理")
        for product in products:
            write_audit_log(object_type="PRODUCT_CATALOG", object_id=product.pk, action="QA_CLEANUP", before_data={"task": TASK, "name_id": str(product.name_id)})
        color_count = len(colors)
        ProductCatalogColor.objects.filter(product_id__in=product_ids).delete()
        ProductCatalog.objects.filter(pk__in=product_ids).delete()
        ProductCatalogName.objects.filter(pk__in=name_ids).delete()
        for account in accounts["accounts"]:
            user = User.objects.select_for_update().get(pk=account["user_id"], username=account["username"])
            employee = Employee.objects.select_for_update().get(pk=account["employee_id"], user=user, employee_code=account["employee_code"])
            for session in Session.objects.all().iterator():
                if str(session.get_decoded().get("_auth_user_id")) == str(user.pk):
                    session.delete()
            employee.delete()
            user.delete()
    remaining = {"names": ProductCatalogName.objects.filter(pk__in=name_ids).count(), "products": ProductCatalog.objects.filter(pk__in=product_ids).count(), "colors": ProductCatalogColor.objects.filter(pk__in=[color.pk for color in colors]).count(), "users": User.objects.filter(pk__in=[item["user_id"] for item in accounts["accounts"]]).count(), "employees": Employee.objects.filter(pk__in=[item["employee_id"] for item in accounts["accounts"]]).count()}
    if any(remaining.values()):
        raise RuntimeError("清理复查仍存在本任务资源")
    print(json.dumps({"action": action, "removed_names": len(names), "removed_products": len(products), "removed_colors": color_count, "removed_accounts": len(accounts["accounts"]), "remaining": remaining, "audit_preserved": True}))
else:
    raise RuntimeError("PRODUCT_CATALOG_QA_ACTION必须为create或cleanup")
