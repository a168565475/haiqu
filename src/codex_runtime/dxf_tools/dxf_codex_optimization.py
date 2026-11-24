"""Codex 只提供有界搜索计划；原轮廓、工艺参数和几何判定始终由本地持有。"""
import copy
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import math
import random
import time

from shapely.geometry import Polygon

from .dxf_geometry import DxfError
from .dxf_nesting import _Deadline, _Search, _parameters, _validate


def _checked_baseline(analysis, parameters, baseline):
    context = _parameters(analysis, parameters)
    width, gap, sets, products, lookup, config = context
    if not isinstance(baseline, dict):
        raise DxfError("NEST_VALIDATION", "缺少可核验的基准排料。")
    length = baseline.get("length_mm")
    if isinstance(length, bool) or not isinstance(length, (int, float)) or not math.isfinite(length) or length <= 0:
        raise DxfError("NEST_VALIDATION", "基准排料总长无效。")
    if any(baseline.get(key) != value for key, value in {
            "width_mm": width, "gap_mm": gap, "set_count": sets, "products_per_set": products,
            "product_quantity": sets * products}.items()):
        raise DxfError("NEST_VALIDATION", "基准排料的工艺参数已变化。")
    placements = baseline.get("placements")
    if not isinstance(placements, list) or len(placements) > 160:
        raise DxfError("NEST_VALIDATION", "基准排料裁片清单无效。")
    for row in placements:
        if (not isinstance(row, dict) or row.get("piece_id") not in lookup
                or type(row.get("copy")) is not int
                or any(isinstance(row.get(key), bool) or not isinstance(row.get(key), (int, float))
                       or not math.isfinite(row[key]) for key in ("angle", "x", "y"))):
            raise DxfError("NEST_VALIDATION", "基准排料坐标或裁片标识无效。")
    # 不相信旧记录中的 passed 标记，重新检查精细轮廓、数量、方向、边界与间距。
    validation = _validate(lookup, config, placements, width, length, gap, sets)
    checked = _result(baseline, context, placements, length, validation)
    return context, checked


def _result(previous, context, placements, length, validation):
    width, gap, sets, products, lookup, config = context
    result = copy.deepcopy(previous)
    consumption = Decimal(str(length)) / Decimal(1000) / Decimal(sets * products)
    area = sum(Polygon(lookup[key]["points"]).area * row["quantity"] * sets for key, row in config.items())
    result.update(width_mm=width, gap_mm=gap, set_count=sets, products_per_set=products,
                  product_quantity=sets * products, length_mm=length, placements=copy.deepcopy(placements),
                  validation=validation, consumption_m=format(consumption, "f"),
                  consumption_rounded_m=format(consumption.quantize(Decimal("0.0001"), rounding=ROUND_CEILING), "f"),
                  utilization_percent=area / (width * length) * 100,
                  piece_names={key: row["name"] for key, row in config.items()})
    return result


def _outline(polygon, budget):
    guide = polygon
    tolerance = max(polygon.bounds[2] - polygon.bounds[0], polygon.bounds[3] - polygon.bounds[1]) * 0.00001
    while len(guide.exterior.coords) - 1 > budget:
        guide = polygon.simplify(tolerance, preserve_topology=True)
        tolerance *= 2
    return [[round(x, 6), round(y, 6)] for x, y in list(guide.exterior.coords)[:-1]]


def make_codex_payload(analysis, parameters, baseline):
    context, checked = _checked_baseline(analysis, parameters, baseline)
    width, gap, sets, products, lookup, config = context
    budget = max(8, min(96, 2500 // len(lookup)))
    instances = [{"instance_id": f"{key}:{index}", "piece_id": key, "copy": index}
                 for key, row in config.items() for index in range(row["quantity"] * sets)]
    pieces = []
    for key, piece in lookup.items():
        polygon = Polygon(piece["points"])
        left, bottom, right, top = polygon.bounds
        pieces.append({"piece_id": key, "width_mm": right - left, "height_mm": top - bottom,
                       "area_mm2": polygon.area, "allowed_angles": list(config[key]["angles"]),
                       "outline_mm": _outline(polygon, budget)})
    # 指纹覆盖完整精细几何和当前基准；模型只接收近似轮廓，不接收原图文字或其他业务数据。
    fingerprint_data = {"geometry": [{"id": key, "points": piece["points"],
        "curve_tolerance_mm": piece.get("curve_tolerance_mm", 0)} for key, piece in lookup.items()],
        "width": width, "gap": gap, "sets": sets, "products": products,
        "instances": instances, "angles": {key: list(row["angles"]) for key, row in config.items()},
        "baseline_length": checked["length_mm"], "baseline_placements": checked["placements"]}
    fingerprint = hashlib.sha256(json.dumps(fingerprint_data, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"schema_version": 1, "constraint_fingerprint": fingerprint,
            "width_mm": width, "gap_mm": gap, "set_count": sets, "products_per_set": products,
            "pieces": pieces, "instances": instances,
            "baseline": {"length_mm": checked["length_mm"], "consumption_m": checked["consumption_m"],
                "placements": [{"instance_id": f"{p['piece_id']}:{p['copy']}", "angle": p["angle"],
                                "x": p["x"], "y": p["y"]} for p in checked["placements"]]}}


def validate_codex_proposal(payload, response):
    def reject():
        raise DxfError("CODEX_INVALID_PROPOSAL", "Codex 建议不符合原始裁片或允许方向，未采用。")

    try:
        if len(json.dumps(response, allow_nan=False, ensure_ascii=False).encode("utf-8")) > 192 * 1024:
            reject()
    except (ValueError, TypeError, RecursionError):
        reject()
    if (not isinstance(response, dict) or set(response) != {"schema_version", "constraint_fingerprint", "plans"}
            or type(response.get("schema_version")) is not int or response["schema_version"] != 1
            or response.get("constraint_fingerprint") != payload["constraint_fingerprint"]):
        reject()
    plans = response["plans"]
    if not isinstance(plans, list) or not 1 <= len(plans) <= 3:
        reject()
    instances = {row["instance_id"]: row for row in payload["instances"]}
    angles = {row["piece_id"]: set(row["allowed_angles"]) for row in payload["pieces"]}
    for plan in plans:
        if (not isinstance(plan, dict) or set(plan) != {"reason", "order"}
                or not isinstance(plan["reason"], str) or len(plan["reason"]) > 240
                or not isinstance(plan["order"], list) or len(plan["order"]) != len(instances)):
            reject()
        seen = set()
        for row in plan["order"]:
            if (not isinstance(row, dict) or set(row) != {"instance_id", "angles"}
                    or not isinstance(row["instance_id"], str) or row["instance_id"] not in instances
                    or row["instance_id"] in seen):
                reject()
            allowed = angles[instances[row["instance_id"]]["piece_id"]]
            selected = row["angles"]
            if (not isinstance(selected, list) or not 1 <= len(selected) <= 24
                    or any(type(angle) is not int or angle not in allowed for angle in selected)
                    or len(set(selected)) != len(selected)):
                reject()
            seen.add(row["instance_id"])
    return copy.deepcopy(response)


def refine_with_codex(analysis, parameters, baseline, proposal, timeout_seconds=120):
    start = time.monotonic()
    context, best = _checked_baseline(analysis, parameters, baseline)
    width, gap, sets, _products, lookup, config = context
    payload = make_codex_payload(analysis, parameters, best)
    plans = validate_codex_proposal(payload, proposal)["plans"]
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or timeout_seconds < 0):
        raise DxfError("NEST_PARAMETERS", "Codex 本地验证的时间预算无效。")
    deadline = start + min(timeout_seconds, 120) * 0.85
    search = _Search(lookup, config, width, gap, deadline)
    instance_map = {row["instance_id"]: (row["piece_id"], row["copy"]) for row in payload["instances"]}
    evaluated, rejected, valid, selected, timed_out = 0, 0, 0, None, False
    for index, plan in enumerate(plans):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            break
        # 每个计划分得剩余预算的一份；同一次优化共享禁放区缓存，慢计划不会吃完后续机会。
        search.deadline = min(deadline, time.monotonic() + remaining / (len(plans) - index))
        try:
            order, variants = [], {}
            for row in plan["order"]:
                search.check()
                identity = instance_map[row["instance_id"]]
                order.append(identity)
                fits = []
                for angle in row["angles"]:
                    key = (identity[0], angle)
                    shape = search.shape(key)
                    if shape.envelope.bounds[2] - shape.envelope.bounds[0] <= width + 1e-9:
                        fits.append(key)
                variants[identity] = fits
            if any(not values for values in variants.values()):
                rejected += 1
                evaluated += 1
                continue
            candidate = search.place(order, {}, best["length_mm"], random.Random(7321 + index), instance_variants=variants)
            evaluated += 1
            if candidate is None:
                rejected += 1
                continue
            placements, length = candidate
            try:
                validation = _validate(lookup, config, placements, width, length, gap, sets)
            except DxfError as error:
                if error.code != "NEST_VALIDATION":
                    raise
                rejected += 1
                continue
            valid += 1
            if length < best["length_mm"] - 1e-7:
                best = _result(best, context, placements, length, validation)
                best["algorithm"] = "codex_guided_nfp_v1"
                selected = index
        except _Deadline:
            timed_out = True
    # 再查最终坐标，输出不继承模型声称的校验、利用率或单耗。
    validation = _validate(lookup, config, best["placements"], width, best["length_mm"], gap, sets)
    best = _result(best, context, best["placements"], best["length_mm"], validation)
    best["optimization"] = {"status": "IMPROVED" if selected is not None else "UNCHANGED",
        "baseline_length_mm": baseline["length_mm"], "candidate_count": len(plans),
        "evaluated_count": evaluated, "valid_candidate_count": valid, "rejected_count": rejected,
        "selected_plan_index": selected, "timed_out": timed_out,
        "elapsed_seconds": time.monotonic() - start,
        "reason": plans[selected]["reason"] if selected is not None else "未找到比基准更短且通过几何校验的方案，保留基准。"}
    return best
