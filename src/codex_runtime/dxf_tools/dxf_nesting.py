"""限时二维排料：先保留完整安全基准，再用禁放区搜索改进。"""

import math
import random
import time
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING

from shapely import affinity, constrained_delaunay_triangles, union_all
from shapely.geometry import MultiPoint, Polygon, box

from .dxf_geometry import CURVE_TOLERANCE_MM, DxfError, MAX_PIECE_POINTS, MAX_TOTAL_POINTS

ROTATIONS = {"fixed": (0,), "half_turn": (0, 180), "quarter_turn": (0, 90, 180, 270),
             "free": tuple(range(0, 360, 15))}
MAX_EXPANDED_POINTS = 40000


def _number(value, name, minimum, maximum, integer=False):
    if isinstance(value, bool):
        raise DxfError("NEST_PARAMETERS", f"{name}必须为有效数字。")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as error:
        raise DxfError("NEST_PARAMETERS", f"{name}必须为有效数字。") from error
    if not math.isfinite(number) or not minimum <= number <= maximum or (integer and number != int(number)):
        raise DxfError("NEST_PARAMETERS", f"{name}超出有效范围。")
    return int(number) if integer else number


def _parameters(analysis, parameters):
    if not isinstance(analysis, dict) or not isinstance(parameters, dict):
        raise DxfError("NEST_PARAMETERS", "排料输入无效。")
    width = _number(parameters.get("width_mm"), "净门幅", 0.001, 1000000)
    gap = _number(parameters.get("gap_mm", 0), "片间距", 0, 1000)
    sets = _number(parameters.get("set_count"), "混排套数", 1, 1000000, True)
    products = _number(parameters.get("products_per_set"), "每套对应成品数", 1, 1000000, True)
    pieces = analysis.get("pieces")
    rows = parameters.get("pieces")
    if not isinstance(pieces, list) or not pieces or not isinstance(rows, list):
        raise DxfError("NEST_PARAMETERS", "请选择裁片并填写每套数量和方向。")
    lookup = {piece["id"]: piece for piece in pieces}
    if len(lookup) != len(pieces) or len(pieces) > 160 or len(rows) != len(pieces):
        raise DxfError("NEST_PARAMETERS", "裁片清单不完整或有重复。")
    configured = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("piece_id") not in lookup or row["piece_id"] in configured:
            raise DxfError("NEST_PARAMETERS", "裁片清单不完整或有重复。")
        mode = row.get("rotation_mode")
        if mode not in ROTATIONS:
            raise DxfError("NEST_PARAMETERS", "裁片旋转方向无效。")
        quantity = _number(row.get("quantity"), "每套片数", 1, 160, True)
        name = row.get("name", lookup[row["piece_id"]]["name"])
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise DxfError("NEST_PARAMETERS", "裁片名称应为 1 至 80 个字符。")
        configured[row["piece_id"]] = {"quantity": quantity, "angles": ROTATIONS[mode], "name": name.strip()}
    if sum(row["quantity"] * sets for row in configured.values()) > 160:
        raise DxfError("NEST_TOO_MANY_PIECES", "本次排料最多支持 160 片，请减少混排套数或片数。")
    total_points, expanded_points = 0, 0
    for piece in pieces:
        points = piece.get("points")
        if not isinstance(points, list) or not 4 <= len(points) <= MAX_PIECE_POINTS:
            raise DxfError("DXF_COMPLEXITY", "裁片轮廓顶点数无效。")
        if any(not isinstance(p, (list, tuple)) or len(p) != 2
               or any(not isinstance(c, (int, float)) or not math.isfinite(c) for c in p) for p in points):
            raise DxfError("DXF_INVALID_CONTOUR", "裁片轮廓坐标无效。")
        polygon = Polygon(points)
        if not polygon.is_valid or polygon.area <= 0 or points[0] != points[-1]:
            raise DxfError("DXF_INVALID_CONTOUR", "裁片轮廓无效。")
        total_points += len(points)
        expanded_points += len(points) * configured[piece["id"]]["quantity"] * sets
    if total_points > MAX_TOTAL_POINTS:
        raise DxfError("DXF_COMPLEXITY", "图纸超过 20000 个计算顶点。")
    if expanded_points > MAX_EXPANDED_POINTS:
        raise DxfError("DXF_COMPLEXITY", "本次混排展开后超过 40000 个轮廓顶点，请减少套数或简化图纸。")
    return width, gap, sets, products, lookup, configured


def transformed_polygon(piece, placement):
    rotated = affinity.rotate(Polygon(piece["points"]), placement["angle"], origin=(0, 0))
    left, bottom, _, _ = rotated.bounds
    normalized = affinity.translate(rotated, -left, -bottom)
    return affinity.translate(normalized, placement["x"], placement["y"])


@dataclass
class _Shape:
    native: Polygon
    fine: Polygon
    envelope: Polygon
    clearance: Polygon
    parts: list | None = None


class _Deadline(Exception):
    pass


class _Search:
    def __init__(self, lookup, config, width, gap, deadline):
        self.lookup, self.config, self.width, self.gap = lookup, config, width, gap
        self.deadline = deadline
        self.shapes, self.forbidden = {}, {}

    def check(self):
        if time.monotonic() >= self.deadline:
            raise _Deadline

    def shape(self, key):
        if key not in self.shapes:
            self.check()
            piece_id, angle = key
            piece = self.lookup[piece_id]
            native = transformed_polygon(piece, {"angle": angle, "x": 0, "y": 0})
            curve = min(CURVE_TOLERANCE_MM, max(0, float(piece.get("curve_tolerance_mm", 0))))
            fine = native.buffer(curve, join_style=2) if curve else native
            envelope = fine
            if len(native.exterior.coords) > 30:
                candidate = fine.simplify(0.35, preserve_topology=True).buffer(0.355, join_style=2)
                # 只有确实包含精细轮廓时才使用简化包络；原始点始终保留用于出图。
                if (candidate.is_valid and candidate.covers(fine)
                        and candidate.bounds[2] - candidate.bounds[0] <= self.width):
                    envelope = candidate
            clearance = envelope.buffer(self.gap / 2, join_style=2) if self.gap else envelope
            self.shapes[key] = _Shape(native, fine, envelope, clearance)
        return self.shapes[key]

    def variants(self, piece_id):
        fits = []
        for angle in self.config[piece_id]["angles"]:
            shape = self.shape((piece_id, angle))
            left, _, right, _ = shape.envelope.bounds
            if (right - left <= self.width + 1e-9
                    and not any(shape.native.hausdorff_distance(self.shape(previous).native) < 1e-8 for previous in fits)):
                fits.append((piece_id, angle))
        if not fits:
            raise DxfError("NEST_TOO_WIDE", "有裁片在所选方向下超过净门幅，请调整门幅或方向。")
        return fits

    def parts(self, key):
        shape = self.shape(key)
        if shape.parts is not None:
            return shape.parts
        self.check()
        polygon = shape.clearance
        hull = polygon.convex_hull
        if hull.area - polygon.area < 1e-8:
            shape.parts = [hull]
            return shape.parts
        triangles = list(constrained_delaunay_triangles(polygon).geoms)
        self.check()
        if union_all(triangles).symmetric_difference(polygon).area > 1e-7:
            # 凸包只是更保守的搜索障碍，绝不替代输出轮廓。
            shape.parts = [hull]
            return shape.parts
        if len(triangles) > 200:
            shape.parts = [hull]
            return shape.parts
        changed = True
        while changed and len(triangles) > 1:
            self.check()
            changed = False
            for i in range(len(triangles)):
                self.check()
                for j in range(i):
                    if not triangles[i].touches(triangles[j]):
                        continue
                    joined = triangles[i].union(triangles[j])
                    if joined.geom_type == "Polygon" and joined.convex_hull.area - joined.area < 1e-7:
                        triangles[j] = joined.convex_hull
                        triangles.pop(i)
                        changed = True
                        break
                if changed:
                    break
        shape.parts = triangles if len(triangles) <= 40 else [hull]
        return shape.parts

    def nfp(self, first, second):
        key = (first, second)
        if key not in self.forbidden:
            sums = []
            for a in self.parts(first):
                for b in self.parts(second):
                    self.check()
                    points = [(x1 - x2, y1 - y2) for x1, y1 in a.exterior.coords[:-1]
                              for x2, y2 in b.exterior.coords[:-1]]
                    sums.append(MultiPoint(points).convex_hull)
            self.check()
            if len(self.forbidden) >= 512:
                self.forbidden.pop(next(iter(self.forbidden)))
            self.forbidden[key] = union_all(sums)
        return self.forbidden[key]

    def baseline(self, order, variants):
        shelves, placed = [], []
        height = 0
        for piece_id, copy in order:
            self.check()
            best = None
            for key in variants[piece_id]:
                left, bottom, right, top = self.shape(key).envelope.bounds
                width, h = right - left, top - bottom
                for shelf in shelves:
                    if h <= shelf["height"] + 1e-9 and shelf["next_x"] + width <= self.width + 1e-9:
                        candidate = (0, shelf["y"], shelf["next_x"], key, shelf, left, bottom, width, h)
                        if best is None or candidate[:3] < best[:3]:
                            best = candidate
                candidate = (h, height + (self.gap if placed else 0), 0, key, None, left, bottom, width, h)
                if best is None or candidate[:3] < best[:3]:
                    best = candidate
            _, y, x, key, shelf, left, bottom, width, h = best
            if shelf is None:
                shelf = {"y": y, "height": h, "next_x": 0}
                shelves.append(shelf)
                height = y + h
            shelf["next_x"] = x + width + self.gap
            placed.append({"piece_id": piece_id, "copy": copy, "angle": key[1], "x": x - left, "y": y - bottom})
        return placed, height

    def place(self, order, variants, ceiling, rng, *, instance_variants=None):
        placed, occupied, height = [], [], 0
        for piece_id, copy in order:
            self.check()
            best = None
            keys = list(instance_variants[(piece_id, copy)] if instance_variants is not None else variants[piece_id])
            if instance_variants is None:
                rng.shuffle(keys)
            for key in keys:
                self.check()
                shape = self.shape(key)
                left, bottom, right, top = shape.envelope.bounds
                low_x, high_x, low_y = -left, self.width - right, -bottom
                high_y = min(ceiling - top, height + self.gap - bottom)
                if high_y < low_y - 1e-8:
                    continue
                # 零宽/零高可行域单独保留，避免 box 退化后丢失贴边解。
                domain = box(low_x, low_y, max(low_x, high_x), max(low_y, high_y))
                obstacles = []
                for previous in placed:
                    self.check()
                    forbidden = self.nfp((previous["piece_id"], previous["angle"]), key)
                    obstacles.append(affinity.translate(forbidden, previous["x"], previous["y"]))
                free = domain.difference(union_all(obstacles)) if obstacles else domain
                candidates = list(_vertices(free))
                candidates.extend([(low_x, low_y), (high_x, low_y), (low_x, high_y), (high_x, high_y)])
                candidates = sorted(set(candidates), key=lambda p: (p[1], p[0]))
                for x, y in candidates:
                    self.check()
                    for dx, dy in ((0, 0), (0, 1e-6), (1e-6, 0), (-1e-6, 1e-6)):
                        px, py = x + dx, y + dy
                        if px < low_x - 1e-9 or px > high_x + 1e-9 or py < low_y - 1e-9 or py > high_y + 1e-9:
                            continue
                        moved = affinity.translate(shape.envelope, px, py)
                        moved_bounds = moved.bounds
                        nearby = [other for other, bounds in occupied
                                  if not (moved_bounds[2] + self.gap < bounds[0]
                                          or bounds[2] + self.gap < moved_bounds[0]
                                          or moved_bounds[3] + self.gap < bounds[1]
                                          or bounds[3] + self.gap < moved_bounds[1])]
                        if any(moved.intersection(other).area > 0 or moved.distance(other) < self.gap - 1e-8
                               for other in nearby):
                            continue
                        score = (max(height, py + top), py, px)
                        if best is None or score < best[0]:
                            best = (score, {"piece_id": piece_id, "copy": copy, "angle": key[1], "x": px, "y": py}, moved)
                        break
                    if best and best[0][1] <= y:
                        break
            if best is None:
                return None
            height = best[0][0]
            placed.append(best[1])
            occupied.append((best[2], best[2].bounds))
        return placed, height


def _vertices(geometry):
    if geometry.is_empty:
        return
    if geometry.geom_type == "Polygon":
        yield from geometry.exterior.coords
        for ring in geometry.interiors:
            yield from ring.coords
    elif geometry.geom_type in {"Point", "LineString", "LinearRing"}:
        yield from geometry.coords
    else:
        for child in geometry.geoms:
            yield from _vertices(child)


def _validate(lookup, configured, placements, width, length, gap, sets):
    expected = Counter({key: row["quantity"] * sets for key, row in configured.items()})
    if Counter(p["piece_id"] for p in placements) != expected:
        raise DxfError("NEST_VALIDATION", "排料片数与要求不一致。")
    seen, polygons, fine_polygons = set(), [], []
    for placement in placements:
        piece_id, copy = placement["piece_id"], placement["copy"]
        if (piece_id, copy) in seen or not isinstance(copy, int) or not 0 <= copy < expected[piece_id]:
            raise DxfError("NEST_VALIDATION", "排料副本重复或缺失。")
        seen.add((piece_id, copy))
        if placement["angle"] not in configured[piece_id]["angles"]:
            raise DxfError("NEST_VALIDATION", "排料旋转方向与要求不一致。")
        polygon = transformed_polygon(lookup[piece_id], placement)
        curve = float(lookup[piece_id].get("curve_tolerance_mm", 0))
        fine = polygon.buffer(curve, join_style=2) if curve else polygon
        left, bottom, right, top = fine.bounds
        if not polygon.is_valid or left < -1e-7 or bottom < -1e-7 or right > width + 1e-7 or top > length + 1e-7:
            raise DxfError("NEST_VALIDATION", "排料轮廓无效或超出布框。")
        polygons.append(polygon)
        fine_polygons.append(fine)
    minimum_gap, checks = None, 0
    for i, polygon in enumerate(polygons):
        for j, previous in enumerate(polygons[:i]):
            checks += 1
            if polygon.intersection(previous).area > 0:
                raise DxfError("NEST_VALIDATION", "精细轮廓发生重叠，结果不可采用。")
            distance = fine_polygons[i].distance(fine_polygons[j])
            if fine_polygons[i].intersection(fine_polygons[j]).area > 1e-10 or distance < gap - 1e-7:
                raise DxfError("NEST_VALIDATION", "曲线安全轮廓或片间距检查未通过。")
            minimum_gap = distance if minimum_gap is None else min(minimum_gap, distance)
    return {"passed": True, "piece_count": len(placements), "pair_checks": checks,
            "max_overlap_area_mm2": 0, "minimum_gap_mm": minimum_gap, "precision_mm": CURVE_TOLERANCE_MM,
            "quantities_valid": True, "bounds_valid": True, "rotations_valid": True, "overlap_free": True}


def nest_pieces(analysis, parameters, timeout_seconds=120):
    start = time.monotonic()
    if not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise DxfError("NEST_TIMEOUT", "排料时间预算已耗尽，未生成完整结果。")
    width, gap, sets, products, lookup, config = _parameters(analysis, parameters)
    # 预留最终精细检查时间；worker 仍在外层提供进程硬超时。
    deadline = start + min(float(timeout_seconds), 120) * 0.85
    search = _Search(lookup, config, width, gap, deadline)
    order = [(key, copy) for key, row in config.items() for copy in range(row["quantity"] * sets)]
    order.sort(key=lambda item: Polygon(lookup[item[0]]["points"]).area, reverse=True)
    try:
        variants = {key: search.variants(key) for key in lookup}
        best, length = search.baseline(order, variants)
        validation = _validate(lookup, config, best, width, length, gap, sets)
    except _Deadline as error:
        raise DxfError("NEST_TIMEOUT", "时间预算内未生成完整基准排料，请减少裁片或方向。") from error
    rng = random.Random(7321)
    iterations, limited = 0, False
    best_order = order.copy()
    try:
        # 缓存仅属于当前请求；不读取外部 pickle，不与其他任务共享几何。
        while iterations < 80:
            search.check()
            current = best_order.copy()
            if iterations and len(current) > 1:
                for _ in range(1 + iterations % 4):
                    a, b = rng.sample(range(len(current)), 2)
                    current[a], current[b] = current[b], current[a]
            # 自由角度先取得正交方向的完整改进，再扩展到全部 15 度候选。
            active_variants = ({key: [variant for variant in values if variant[1] % 90 == 0] or values
                                for key, values in variants.items()} if iterations < 2 else variants)
            candidate = search.place(current, active_variants, length, rng)
            iterations += 1
            if candidate is not None and candidate[1] < length - 1e-7:
                candidate_validation = _validate(lookup, config, candidate[0], width, candidate[1], gap, sets)
                best, length = candidate
                validation = candidate_validation
                best_order = current
    except _Deadline:
        limited = True
    validation = _validate(lookup, config, best, width, length, gap, sets)
    product_quantity = sets * products
    consumption = Decimal(str(length)) / Decimal(1000) / Decimal(product_quantity)
    total_area = sum(Polygon(lookup[p["piece_id"]]["points"]).area for p in best)
    warnings = ["排料为有限角度、有限时间内的可行结果，不保证全局最优。"]
    if limited:
        warnings.append("优化已到时间上限，保留当前已校验完整排料。")
    return {"width_mm": width, "length_mm": length, "gap_mm": gap, "set_count": sets,
            "products_per_set": products, "product_quantity": product_quantity,
            "consumption_m": format(consumption, "f"),
            "consumption_rounded_m": format(consumption.quantize(Decimal("0.0001"), rounding=ROUND_CEILING), "f"),
            "utilization_percent": total_area / (width * length) * 100, "placements": best,
            "validation": validation, "warnings": warnings,
            "piece_names": {key: row["name"] for key, row in config.items()},
            "iterations": iterations, "elapsed_seconds": time.monotonic() - start,
            "algorithm": "bounded_nfp_v1"}
