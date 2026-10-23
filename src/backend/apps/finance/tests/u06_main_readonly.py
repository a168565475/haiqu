"""主库只读和XLSX独立比对；不输出真实银行资料。"""
import base64
import hashlib
import json
import os
import sys
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from django.conf import settings
from django.db import connection, transaction
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone
from apps.access_control.models import RoleActionGrant
from apps.organizations.models import EmployeeRoleAssignment, RoleProfile
from apps.finance.models import FinanceAccount, AccountingSubject
from apps.finance.selectors import available_cny_accounts


def digest(value):
    return hashlib.sha256(json.dumps(value, default=str, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def rows_from_original(encoded, expected):
    content = base64.b64decode(encoded, validate=True)
    assert hashlib.sha256(content).hexdigest() == expected, "Source SHA256 mismatch"
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(BytesIO(content)) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ["".join(item.itertext()) for item in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        result = []
        for row in sheet.findall("s:sheetData/s:row", ns):
            values = {}
            for cell in row.findall("s:c", ns):
                assert cell.find("s:f", ns) is None, "Formula in original source"
                col = "".join(char for char in cell.attrib["r"] if char.isalpha())
                value = cell.find("s:v", ns)
                text = value.text if value is not None else ""
                if cell.get("t") == "s":
                    text = shared[int(text)]
                elif cell.get("t") == "inlineStr":
                    text = "".join(cell.find("s:is", ns).itertext())
                values[col] = text
            result.append(values)
    return result


def main():
    sources = json.load(sys.stdin)
    account_rows = rows_from_original(sources["accounts"], "ff72831bb26ca1156f5283e6b4e98865e2b02175ff4809cc45749f04bbbe67d2")
    subject_rows = rows_from_original(sources["subjects"], "367e38a3c912d53eac959cf428b251dfdf8c3f818a6a3b680d2a6c9055fc9666")
    assert connection.settings_dict["NAME"] == "haiqu_erp"
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SHOW transaction_read_only")
            assert cursor.fetchone()[0] == "on"
        tables = connection.introspection.table_names()
        loader = MigrationLoader(connection)
        applied = sorted(name for app, name in loader.applied_migrations if app == "finance")
        pending = sorted(name for app, name in loader.disk_migrations if app == "finance" and (app, name) not in loader.applied_migrations)
        headers = {value: key for key, value in account_rows[0].items()}
        field_headers = {"account_type": "账户类型", "code": "账户编码", "category": "账户类别", "name": "账户名称", "account_number": "账户账号", "status": "账户状态"}
        matches = []
        for index, row in enumerate(account_rows[1:], 2):
            account = FinanceAccount.objects.select_related("currency").get(code=row[headers["账户编码"]])
            fields = {}
            for field, header in field_headers.items():
                value = row[headers[header]]
                if field == "status":
                    value = {"启用": "ACTIVE", "停用": "INACTIVE"}.get(value, value)
                fields[field] = getattr(account, field) == value
            fields["currency"] = row[headers["币种"]] in (account.currency.code, account.currency.chinese_name)
            matches.append({"source_row": index, "matches": fields, "currency": account.currency.code, "number_length": len(account.account_number), "account_number_is_text": isinstance(account.account_number, str)})
        subject_headers = {value: key for key, value in subject_rows[0].items()}
        paths = {tuple(row[subject_headers[name]].strip() for name in ("费用类型", "一级科目", "二级科目")) for row in subject_rows[1:]}
        subject_exists = AccountingSubject._meta.db_table in tables
        actual = set(AccountingSubject.objects.filter(level=3).values_list("parent__parent__name", "parent__name", "name")) if subject_exists else set()
        grants = list(RoleActionGrant.objects.order_by("id").values())
        assignments = list(EmployeeRoleAssignment.objects.order_by("id").values())
        finance_grants = list(RoleActionGrant.objects.filter(permission__content_type__app_label="finance").order_by("role__role_code", "permission__codename").values("role__role_code", "permission__codename", "scope"))
        group_links = list(RoleProfile._meta.get_field("auth_group").related_model.permissions.through.objects.order_by("id").values())
        result = {"captured_at": timezone.now().isoformat(), "database": "haiqu_erp", "read_only": True,
            "finance_applied": applied, "finance_pending": pending, "finance_tables": sorted(x for x in tables if x.startswith("finance_")),
            "accounts": {"count": FinanceAccount.objects.count(), "source_hash_verified": True, "independent_xml_comparison": matches, "all_seven_fields_match": all(all(item["matches"].values()) for item in matches),
                "cny_options_count": available_cny_accounts().count(), "option_currencies": sorted(set(available_cny_accounts().values_list("currency__code", flat=True)))},
            "subjects": {"source_hash_verified": True, "expected_paths": len(paths), "expected_nodes": len({p[:i] for p in paths for i in (1, 2, 3)}), "table_exists": subject_exists, "actual_leaf_count": len(actual), "exact_path_match": actual == paths},
            "finance_grants": finance_grants, "all_grants_sha256": digest(grants), "employee_assignments_sha256": digest(assignments), "group_permission_links_sha256": digest(group_links),
            "accounts_sha256": digest(list(FinanceAccount.objects.order_by("id").values())),
            "file_scan_enabled": settings.FILE_VIRUS_SCAN_ENABLED,
            "real_employee_auth": "UNKNOWN: no existing authenticated session supplied to U06; no authentication change attempted"}
        print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
