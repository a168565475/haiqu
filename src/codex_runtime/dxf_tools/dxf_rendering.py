"""使用同一组经过校验的坐标生成一幅连续 SVG 与毫米 R12 DXF。"""

import io
import re
from html import escape

import ezdxf

from .dxf_geometry import DxfError
from .dxf_nesting import transformed_polygon


def _xml_text(value):
    return escape(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", "\ufffd", value))


def _instances(analysis, result):
    if not result.get("validation", {}).get("passed"):
        raise DxfError("NEST_VALIDATION", "未经完整校验的排料不能导出。")
    lookup = {piece["id"]: piece for piece in analysis["pieces"]}
    for placement in result["placements"]:
        piece = lookup[placement["piece_id"]]
        name = result.get("piece_names", {}).get(piece["id"], piece["name"])
        yield piece, placement, transformed_polygon(piece, placement), name


def render_svg(analysis, result):
    width, length = result["width_mm"], result["length_mm"]
    colors = ("#dbeafe", "#dcfce7", "#fef3c7", "#fce7f3", "#e0e7ff", "#cffafe")
    stroke = max(0.15, width / 1600)
    font = max(3, min(12, width / 100))
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.9f} {length:.9f}" '
             f'width="{width:.6f}mm" height="{length:.6f}mm" role="img" aria-label="完整连续排料图">',
             '<title>完整连续排料图；尺寸单位毫米</title>',
             f'<rect x="0" y="0" width="{width:.9f}" height="{length:.9f}" fill="white" stroke="#334155" stroke-width="{stroke}"/>']
    numbering = {piece["id"]: index for index, piece in enumerate(analysis["pieces"])}
    for piece, placement, polygon, name in _instances(analysis, result):
        index = numbering[piece["id"]]
        label = f"{index + 1}-{placement['copy'] + 1} {name}"
        points = " ".join(f"{x:.9f},{length-y:.9f}" for x, y in polygon.exterior.coords[:-1])
        lines.append(f'<polygon points="{points}" fill="{colors[index % len(colors)]}" stroke="#475569" stroke-width="{stroke}"><title>{_xml_text(label)}</title></polygon>')
        anchor = polygon.representative_point()
        lines.append(f'<text x="{anchor.x:.9f}" y="{length-anchor.y:.9f}" text-anchor="middle" '
                     f'font-family="sans-serif" font-size="{font}" fill="#0f172a">{_xml_text(label)}</text>')
    lines.append("</svg>")
    return "\n".join(lines)


def export_dxf(analysis, result):
    document = ezdxf.new("R12")
    document.header["$LUNITS"] = 2
    document.header["$LUPREC"] = 6
    for index, (_piece, _placement, polygon, _name) in enumerate(_instances(analysis, result), 1):
        layer = f"PIECE_{index:03d}"
        document.layers.add(layer, color=1 + (index - 1) % 7)
        document.modelspace().add_polyline2d(list(polygon.exterior.coords)[:-1], close=True,
                                            dxfattribs={"layer": layer})
    stream = io.StringIO()
    document.write(stream)
    # R12 不含标准 INSUNITS；导入裁剪软件时选择 1 单位 = 1 mm。
    return stream.getvalue().encode("ascii")
