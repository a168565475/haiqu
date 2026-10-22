"""排产列表的外发交期提示；复用详情的授权记录及有效回货凭证。"""
from collections import defaultdict
from decimal import Decimal

from apps.production_scheduling.detail_related import (
    METAL_PERMISSION, OUTSOURCING_PERMISSION, _p4_records, _projected_records,
    _regular_records, _sources_for_tasks, _tube_records,
)


RISK_RANK = {"none": -1, "normal": 0, "unknown": 1, "attention": 2, "slow": 3, "urgent": 4}
FABRIC_CRAFTS = {"CUTTING", "SEWING", "SCREEN_PRINTING", "EMBROIDERY"}


def outsourcing_record_status(record, as_of_date):
    planned = Decimal(record["planned_quantity"]) if record["planned_quantity"] is not None else None
    received = Decimal(record["received_quantity"]) if record["received_quantity"] is not None else None
    remaining = max(Decimal(0), planned - received) if planned is not None and received is not None else None
    due = record["expected_return_date"]
    result = {key: record[key] for key in ("id", "order_number", "craft_name", "part_name", "factory_name", "quantity_unit")}
    result.update(expected_return_date=due.isoformat() if due else None,
                  remaining_quantity=format(remaining, "f") if remaining is not None else None,
                  state="UNKNOWN", risk="unknown", description="回货数量或交期暂不可核对")
    if remaining is None or planned <= 0:
        return result
    if remaining == 0:
        result.update(state="RETURNED", risk="normal", description="已全部回齐")
        return result
    # 已结束但短缺的单据不能显示回齐，也不再假设加工厂还会继续回货。
    if record["status"] in {"COMPLETED", "CLOSED"}:
        result.update(state="SHORTAGE", risk="slow", description="已结束但仍有短缺，请核对后续生产用量")
        return result
    pending = record["status"] in {"PENDING_DISPATCH", "PENDING_HANDOFF"}
    result["state"] = "WAITING" if pending else "IN_PROGRESS"
    if due is None:
        result["description"] = "尚未填写或无权查看外发交期"
        return result
    days = (due - as_of_date).days
    risk = "urgent" if days <= 1 else "slow" if days <= 3 else "attention" if days <= 7 else "normal"
    deadline = f"逾期 {-days} 天" if days < 0 else "今日交期" if days == 0 else f"距交期 {days} 天"
    state = "尚未发出" if pending else "尚未回齐"
    result.update(risk=risk, description=f"{deadline}，{state}" + ("，后续工序有阻塞风险" if risk == "urgent" else ""))
    return result


def outsourcing_stage_status(records, *, allowed=True, complete_scope=True):
    if not allowed or not complete_scope:
        return {"state": "UNKNOWN", "risk": "unknown", "description": "外发信息查看范围不完整", "records": records}
    if not records:
        return {"state": "NONE", "risk": "none", "description": "暂无可查看的有效外发单", "records": []}
    pending = [record for record in records if record["state"] != "RETURNED"]
    if not pending:
        return {"state": "RETURNED", "risk": "normal", "description": "关联外发已全部回齐", "records": records}
    pending.sort(key=lambda row: (-RISK_RANK[row["risk"]], row["expected_return_date"] or "9999-12-31", row["id"]))
    worst = pending[0]
    ordered = pending + [record for record in records if record["state"] == "RETURNED"]
    return {"state": worst["state"], "risk": worst["risk"], "description": worst["description"], "records": ordered}


def outsourcing_order_statuses(records):
    groups = defaultdict(list)
    for record in records:
        groups[(record["order_kind"], record["order_id"])].append(record)
    result = []
    for (kind, order_id), lines in groups.items():
        status = outsourcing_stage_status(lines)
        totals = defaultdict(Decimal)
        unknown_units = set()
        for line in lines:
            unit = line["quantity_unit"]
            if line["remaining_quantity"] is None:
                unknown_units.add(unit)
            else:
                totals[unit] += Decimal(line["remaining_quantity"])
        # 每行先扣除已回数量并封底，不能用某部位多回抵消另一部位欠货；不同单位分开汇总。
        units = sorted(set(totals) | unknown_units)
        remaining = {unit: None if unit in unknown_units else format(totals[unit], "f") for unit in units}
        result.append({
            "id": f"{kind}:{order_id}", "order_number": lines[0]["order_number"],
            "craft_name": lines[0]["craft_name"],
            "factory_name": "、".join(dict.fromkeys(line["factory_name"] or "加工厂未填写" for line in lines)),
            "expected_return_date": lines[0]["expected_return_date"],
            "remaining_quantity": remaining[units[0]] if len(units) == 1 else None,
            "quantity_unit": units[0] if len(units) == 1 else "",
            "remaining_display": " / ".join(f"{quantity if quantity is not None else '—'} {unit}".strip()
                                             for unit, quantity in remaining.items()),
            "state": status["state"], "risk": status["risk"], "description": status["description"],
        })
    return result


def schedule_outsourcing_statuses(schedules, *, request, as_of_date):
    products = [product for schedule in schedules for product in schedule.active_products]
    by_product = {product.product_line_id: product for product in products}
    task_ids = {schedule.production_task_id for schedule in schedules}
    regular_allowed = request.user.has_perm(OUTSOURCING_PERMISSION)
    metal_allowed = request.user.has_perm(METAL_PERMISSION)
    rows = []
    if products and (regular_allowed or metal_allowed):
        originals, reworks, tubes, metal_request = _sources_for_tasks(request, task_ids, by_product)
        originals = originals.exclude(status="CANCELLED")
        tubes = tubes.exclude(status="CANCELLED")
        rows = [*_regular_records(originals, by_product), *_tube_records(tubes, by_product), *_p4_records(reworks, by_product)]
        if metal_allowed:
            rows.extend(_projected_records(metal_request, originals, task_ids, by_product))
    grouped = defaultdict(list)
    for product_id, record in rows:
        stage = "METAL" if record["craft_code"] == "POWDER_COATING" or record["order_kind"] == "P4" else (
            "SEWING" if record["craft_code"] in FABRIC_CRAFTS else None)
        if stage is None:
            continue
        product = by_product[product_id]
        row = outsourcing_record_status(record, as_of_date)
        row.update(order_id=record["order_id"], order_kind=record["order_kind"])
        grouped[(product.schedule_id, stage)].append(row)
    return {str(schedule.pk): {
        stage: outsourcing_stage_status(outsourcing_order_statuses(grouped[(schedule.pk, stage)]),
            allowed=regular_allowed or (stage == "METAL" and metal_allowed),
            complete_scope=len(schedule.active_products) == schedule.stage_product_count)
        for stage in ("METAL", "SEWING")
    } for schedule in schedules}
