"""只计算本次部门归属计划，不自动匹配名称或修改 ERP 历史。"""


def department_plan(member, mappings, *, employee=None, has_history=False, rejection=""):
    def pending(reason):
        return {"status": "PENDING", "reason": reason, "assignments": []}

    if has_history:
        return {"status": "PRESERVED", "reason": "ERP 已有部门归属记录，保留全部历史及当前安排。", "assignments": []}
    if rejection:
        return pending(rejection)
    if employee and (employee["status"] != "ACTIVE" or employee["archived"] or not employee["account_active"]):
        return pending("ERP 员工或账号不可用，暂不补充部门归属。")
    if member["main_department"] is None:
        return pending("来源未明确主部门，请人工核对。")
    by_source = {row["wecom_department_id"]: row for row in mappings["mappings"]}
    assignments = []
    for source_id in member["department"]:
        mapping = by_source.get(source_id)
        if not mapping or not mapping["organization_unit_id"]:
            return pending("来源部门尚未全部映射，请先确认部门对应关系。")
        if not mapping["organization_active"]:
            return pending("映射目标部门已停用或归档，请先核对。")
        existing = next((row for row in assignments if row["department_id"] == mapping["organization_unit_id"]), None)
        if existing:
            existing["is_primary"] = existing["is_primary"] or source_id == member["main_department"]
        else:
            assignments.append({"department_id": mapping["organization_unit_id"],
                                "department_name": mapping["organization_name"],
                                "is_primary": source_id == member["main_department"]})
    if sum(row["is_primary"] for row in assignments) != 1:
        return pending("来源主部门不在成员部门范围内，请人工核对。")
    return {"status": "READY", "reason": "可为归属空白的员工补充部门，不授予角色。", "assignments": assignments}
