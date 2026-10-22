"""企业微信部门来源副本；不写 ERP 组织或角色。"""
from rest_framework.exceptions import ValidationError


def department_snapshot(directory, member):
    values = member.get("department")
    if values is None:
        return None
    if (not isinstance(values, list) or any(type(value) is not int or not 0 < value < 4294967296 for value in values)
            or len(set(values)) != len(values)):
        raise ValidationError("来源成员部门无效或重复。")
    names = {}
    rows = directory.get("departments")
    if not isinstance(rows, list):
        raise ValidationError("来源部门列表缺失。")
    for row in rows:
        if (not isinstance(row, dict) or type(row.get("id")) is not int or not 0 < row["id"] < 4294967296
                or row["id"] in names or (row.get("name") is not None and not isinstance(row["name"], str))):
            raise ValidationError("来源部门无效或重复。")
        names[row["id"]] = row.get("name") or None
    return [{"id": value, "name": names.get(value)} for value in values]
