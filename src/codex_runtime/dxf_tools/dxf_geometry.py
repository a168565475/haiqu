"""有界、只读的二维 DXF 轮廓提取；不修补缺边或改变源图尺寸。"""

import io
import math
import re
from collections import defaultdict

import ezdxf
from ezdxf.filemanagement import dxf_stream_info
from ezdxf.math import OCS, Vec3, arc_angle_span_deg, bulge_to_arc
from shapely import affinity
from shapely.geometry import Point, Polygon

CURVE_TOLERANCE_MM = 0.002
JOIN_TOLERANCE_MM = 0.00001
MAX_PIECE_POINTS = 4000
MAX_TOTAL_POINTS = 20000
MAX_ENTITIES = 10000
UNIT_FACTORS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "inch": 25.4}
UNIT_CODES = {4: "mm", 5: "cm", 6: "m", 1: "inch"}
CUT_TYPES = {"LINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE", "LWPOLYLINE", "POLYLINE"}
ANNOTATIONS = {"DIMENSION", "LEADER", "MLEADER", "POINT", "ATTDEF"}


class DxfError(ValueError):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


def _read_document(source_bytes):
    if not isinstance(source_bytes, bytes) or not source_bytes:
        raise DxfError("DXF_INVALID", "DXF 文件为空或格式无效。")
    if len(source_bytes) > 10 * 1024 * 1024:
        raise DxfError("DXF_TOO_LARGE", "DXF 文件超过 10 MiB。")
    if source_bytes.startswith(b"AutoCAD Binary DXF"):
        raise DxfError("DXF_BINARY", "请导出为文本 DXF，暂不支持二进制 DXF。")
    try:
        info = dxf_stream_info(io.StringIO(source_bytes.decode("latin1"), newline=None))
        text = source_bytes.decode(info.encoding)
        return ezdxf.read(io.StringIO(text, newline=None))
    except (ezdxf.DXFError, UnicodeError, ValueError, IndexError, KeyError) as error:
        raise DxfError("DXF_INVALID", "DXF 结构或声明的文字编码无效，请从 CAD 重新导出。") from error


def _entities(document):
    count = 0

    def visit(items, ancestors=()):
        nonlocal count
        for entity in items:
            count += 1
            if count > MAX_ENTITIES:
                raise DxfError("DXF_COMPLEXITY", "DXF 展开实体超过 10000 个，请精简图纸。")
            kind = entity.dxftype()
            if kind != "INSERT":
                yield entity
                continue
            name = entity.dxf.name
            block = entity.block()
            if (len(ancestors) >= 12 or name in ancestors or block is None
                    or block.block.is_xref or entity.has_extension_dict):
                raise DxfError("DXF_UNSUPPORTED", "暂不支持外部引用、裁剪块、循环或过深的块引用。")
            scales = (entity.dxf.xscale, entity.dxf.yscale, entity.dxf.zscale)
            if (any(not math.isfinite(v) or v <= 0 for v in scales)
                    or not math.isclose(scales[0], scales[1], rel_tol=1e-12)):
                raise DxfError("DXF_UNSUPPORTED", "块引用只支持正数统一缩放，不支持镜像或非均匀缩放。")

            def skipped(_entity, _reason):
                raise DxfError("DXF_UNSUPPORTED", "块中含无法安全展开的实体，请在 CAD 中检查。")

            for insertion in entity.multi_insert() if entity.mcount > 1 else (entity,):
                yield from visit(insertion.virtual_entities(skipped_entity_callback=skipped), ancestors + (name,))
                yield from visit(insertion.attribs, ancestors + (name,))

    yield from visit(document.modelspace())


def _arc_points(center, radius, start, sweep, tolerance):
    if not math.isfinite(radius) or radius <= 0:
        raise DxfError("DXF_INVALID_CONTOUR", "圆弧半径无效。")
    step = 2 * math.acos(max(-1.0, min(1.0, 1 - tolerance / radius)))
    count = max(2, math.ceil(abs(sweep) / max(step, 1e-12)))
    if count > MAX_PIECE_POINTS:
        raise DxfError("DXF_COMPLEXITY", "曲线精度所需顶点过多，请精简图纸。")
    return [(center[0] + radius * math.cos(start + sweep * i / count),
             center[1] + radius * math.sin(start + sweep * i / count)) for i in range(count + 1)]


def _flatten(entity, scale):
    kind = entity.dxftype()
    tolerance = CURVE_TOLERANCE_MM / scale
    curved = kind in {"ARC", "CIRCLE", "ELLIPSE", "SPLINE"}
    if kind == "LINE":
        vertices = [entity.dxf.start, entity.dxf.end]
    elif kind in {"LWPOLYLINE", "POLYLINE"}:
        if kind == "POLYLINE" and not entity.is_2d_polyline:
            raise DxfError("DXF_UNSUPPORTED", "暂不支持三维多段线或网格。")
        if kind == "LWPOLYLINE":
            values = list(entity.get_points("xyb"))
            elevation = entity.dxf.elevation
            closed = entity.closed
            has_width = entity.has_width
        else:
            values = [(v.dxf.location.x, v.dxf.location.y, v.dxf.bulge) for v in entity.vertices]
            elevation = entity.dxf.elevation.z
            closed = entity.is_closed
            has_width = (entity.dxf.default_start_width or entity.dxf.default_end_width
                         or any(v.dxf.start_width or v.dxf.end_width for v in entity.vertices))
        if has_width:
            raise DxfError("DXF_UNSUPPORTED", "带线宽多段线的裁切边界不明确，请导出零宽轮廓。")
        if not values:
            return [], False
        ocs = OCS(entity.dxf.extrusion)
        points = [(values[0][0], values[0][1])]
        for i in range(len(values) if closed else len(values) - 1):
            x, y, bulge = values[i]
            end = values[(i + 1) % len(values)][:2]
            if abs(bulge) < 1e-12 or math.dist((x, y), end) < 1e-12:
                points.append(end)
            else:
                curved = True
                center, _start, _end, radius = bulge_to_arc((x, y), end, bulge)
                arc = _arc_points(center, radius, math.atan2(y - center.y, x - center.x),
                                  4 * math.atan(bulge), tolerance)
                points.extend(arc[1:-1])
                points.append(end)
            if len(points) > MAX_PIECE_POINTS:
                raise DxfError("DXF_COMPLEXITY", "单个轮廓超过 4000 个计算顶点。")
        vertices = (ocs.to_wcs(Vec3(x, y, elevation)) for x, y in points)
    elif kind in {"ARC", "CIRCLE"}:
        start = math.radians(entity.dxf.start_angle) if kind == "ARC" else 0
        sweep = math.radians(arc_angle_span_deg(entity.dxf.start_angle, entity.dxf.end_angle)) if kind == "ARC" else math.tau
        center = entity.dxf.center
        vertices = (entity.ocs().to_wcs(Vec3(x, y, center.z)) for x, y in
                    _arc_points(center, entity.dxf.radius, start, sweep, tolerance))
    else:
        vertices = entity.flattening(tolerance)
    result = []
    for vertex in vertices:
        v = Vec3(vertex)
        if not all(math.isfinite(c) for c in v) or max(abs(c * scale) for c in v) > 1e8:
            raise DxfError("DXF_INVALID_CONTOUR", "轮廓坐标无效或超出支持范围。")
        if abs(v.z * scale) > JOIN_TOLERANCE_MM:
            raise DxfError("DXF_UNSUPPORTED", "只支持位于 XY 平面的二维轮廓。")
        point = (v.x * scale, v.y * scale)
        if not result or math.dist(point, result[-1]) > 1e-9:
            result.append(point)
        if len(result) > MAX_PIECE_POINTS:
            raise DxfError("DXF_COMPLEXITY", "单个轮廓超过 4000 个计算顶点。")
    return result, curved


def _join_contours(segments):
    nodes, cells, edges, adjacency = [], defaultdict(list), [], defaultdict(list)

    def node(point):
        key = (math.floor(point[0] / JOIN_TOLERANCE_MM), math.floor(point[1] / JOIN_TOLERANCE_MM))
        matches = [index for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                   for index in cells[(key[0] + dx, key[1] + dy)]
                   if math.dist(nodes[index], point) <= JOIN_TOLERANCE_MM]
        if len(matches) > 1:
            raise DxfError("DXF_AMBIGUOUS_CONTOUR", "邻近端点存在多种连接方式，请在 CAD 中整理。")
        if matches:
            return matches[0]
        index = len(nodes)
        nodes.append(point)
        cells[key].append(index)
        return index

    for points, curved in segments:
        a, b = node(points[0]), node(points[-1])
        index = len(edges)
        edges.append((a, b, points, curved))
        adjacency[a].append(index)
        adjacency[b].append(index)
    if any(len(indices) != 2 for indices in adjacency.values()):
        raise DxfError("DXF_OPEN_CONTOUR", "轮廓存在断口或分叉；程序不会自动补线。")
    unused = set(range(len(edges)))
    polygons = []
    while unused:
        index = min(unused)
        start, current, points, curved = edges[index]
        chain = list(points)
        unused.remove(index)
        while current != start:
            candidates = [i for i in adjacency[current] if i in unused]
            if len(candidates) != 1:
                raise DxfError("DXF_AMBIGUOUS_CONTOUR", "无法唯一连接外轮廓。")
            index = candidates[0]
            a, b, points, is_curve = edges[index]
            chain.extend(points[1:] if current == a else points[-2::-1])
            current = b if current == a else a
            curved = curved or is_curve
            unused.remove(index)
        chain[-1] = chain[0]
        polygon = Polygon(chain) if len(chain) >= 4 else None
        if polygon is None or not polygon.is_valid or polygon.area <= 1e-8:
            raise DxfError("DXF_INVALID_CONTOUR", "轮廓自交、重复或面积为零，请在 CAD 中修正。")
        if len(chain) > MAX_PIECE_POINTS:
            raise DxfError("DXF_COMPLEXITY", "单个轮廓超过 4000 个计算顶点。")
        polygons.append((polygon, curved))
    if len(polygons) > 160 or sum(len(p.exterior.coords) for p, _ in polygons) > MAX_TOTAL_POINTS:
        raise DxfError("DXF_COMPLEXITY", "图纸超过 160 种裁片或 20000 个计算顶点。")
    for i, (polygon, _) in enumerate(polygons):
        for other, _ in polygons[:i]:
            if polygon.intersection(other).area > 0:
                raise DxfError("DXF_AMBIGUOUS_CONTOUR", "源图轮廓相交或嵌套，无法自动区分外边界与内部线。")
    return sorted(polygons, key=lambda entry: entry[0].bounds[:2])


def analyze_dxf(source_bytes, source_unit="auto"):
    document = _read_document(source_bytes)
    if source_unit != "auto" and source_unit not in UNIT_FACTORS:
        raise DxfError("DXF_UNIT_UNKNOWN", "请选择 mm、cm、m 或 inch。")
    unit = UNIT_CODES.get(document.units) if source_unit == "auto" else source_unit
    if unit is None:
        raise DxfError("DXF_UNIT_UNKNOWN", "DXF 没有可识别的单位，请明确选择源图单位。")
    scale, segments, labels, warnings = UNIT_FACTORS[unit], [], [], []
    total_points = 0
    try:
        for entity in _entities(document):
            kind = entity.dxftype()
            if kind in {"TEXT", "MTEXT", "ATTRIB"}:
                text = entity.plain_text().strip() if kind == "MTEXT" else entity.dxf.text.strip()
                if text and len(text) <= 200:
                    labels.append((text, Point(entity.dxf.insert.x * scale, entity.dxf.insert.y * scale)))
            elif kind in CUT_TYPES:
                points, curved = _flatten(entity, scale)
                total_points += len(points)
                if total_points > MAX_TOTAL_POINTS:
                    raise DxfError("DXF_COMPLEXITY", "图纸超过 20000 个计算顶点。")
                if len(points) < 2:
                    warnings.append("已排除一个零长度实体；请核对轮廓预览。")
                else:
                    segments.append((points, curved))
            elif kind not in ANNOTATIONS:
                raise DxfError("DXF_UNSUPPORTED", f"暂不支持 {kind} 实体，请仅保留二维裁片轮廓。")
    except (ezdxf.DXFError, ArithmeticError, IndexError) as error:
        raise DxfError("DXF_INVALID_CONTOUR", "图纸中存在无法计算的曲线或块引用。") from error
    if not segments:
        raise DxfError("DXF_NO_PIECES", "图纸中没有可识别的裁片轮廓。")
    polygons = _join_contours(segments)
    names = defaultdict(list)
    for text, position in labels:
        if re.match(r"^[+-]?\d+(?:\.\d+)?\s*(?:mm|cm|m|米|毫米|厘米)(?:\b|[^a-z])", text, re.I):
            warnings.append(f"说明文字未作为裁片：{text[:80]}")
            continue
        distances = sorted((p.distance(position), i) for i, (p, _) in enumerate(polygons))
        distance, index = distances[0]
        polygon = polygons[index][0]
        width, height = polygon.bounds[2] - polygon.bounds[0], polygon.bounds[3] - polygon.bounds[1]
        if distance > max(width, height) or (len(distances) > 1 and distances[1][0] - distance < 1e-5):
            warnings.append("存在无法唯一关联的文字，请核对裁片名称和数量。")
            continue
        names[index].append(text)
    pieces = []
    for index, (polygon, curved) in enumerate(polygons):
        name, quantity = f"裁片 {index + 1}", 1
        if len(names[index]) == 1:
            text = names[index][0]
            match = re.fullmatch(r"(.+?)\s*[*×xX]\s*(\d+)", text)
            name = (match.group(1).strip() if match else text)[:80]
            if match:
                quantity = int(match.group(2))
                if not 1 <= quantity <= 160:
                    quantity = 1
                    warnings.append(f"{name} 的文字数量无效，请重新填写。")
        elif names[index]:
            warnings.append(f"裁片 {index + 1} 对应多条文字，请核对名称和每套数量。")
        left, bottom, right, top = polygon.bounds
        normalized = affinity.translate(polygon, -left, -bottom)
        pieces.append({"id": f"P{index + 1:03d}", "name": name, "quantity": quantity,
                       "points": [list(p) for p in normalized.exterior.coords], "area_mm2": polygon.area,
                       "width_mm": right - left, "height_mm": top - bottom,
                       "curve_tolerance_mm": CURVE_TOLERANCE_MM if curved else 0})
    warnings.append("名称和每套片数为识别建议，请核对后计算；未计入无轮廓说明、缝份和生产损耗。")
    return {"unit": "mm", "source_unit": unit, "pieces": pieces, "warnings": list(dict.fromkeys(warnings))}
