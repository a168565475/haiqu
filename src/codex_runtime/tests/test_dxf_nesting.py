import io
import math
import unittest
from decimal import Decimal
from xml.etree import ElementTree

import ezdxf
from shapely import affinity
from shapely.geometry import Polygon

from codex_runtime.dxf_tools.dxf_geometry import DxfError, analyze_dxf
from codex_runtime.dxf_tools.dxf_nesting import nest_pieces
from codex_runtime.dxf_tools.dxf_rendering import export_dxf, render_svg
from codex_runtime.tests.test_dxf_geometry import dxf_bytes, rectangle


def drawing(width=100, height=50):
    doc = ezdxf.new(units=4)
    rectangle(doc.modelspace(), width=width, height=height)
    return analyze_dxf(dxf_bytes(doc))


def parameters(analysis, **changes):
    result = {"width_mm": 200, "gap_mm": 0, "set_count": 2, "products_per_set": 1,
              "pieces": [{"piece_id": p["id"], "quantity": 1, "rotation_mode": "fixed"}
                         for p in analysis["pieces"]]}
    result.update(changes)
    return result


class DxfNestingTests(unittest.TestCase):
    def test_complete_layout_counts_and_per_product_ceiling(self):
        analysis = drawing(width=100, height=50.01)
        config = parameters(analysis, width_mm=100, products_per_set=3)
        result = nest_pieces(analysis, config, timeout_seconds=0.5)
        self.assertEqual(len(result["placements"]), 2)
        self.assertEqual(result["product_quantity"], 6)
        self.assertEqual(result["consumption_rounded_m"], "0.0167")
        self.assertGreaterEqual(Decimal(result["consumption_rounded_m"]), Decimal(result["consumption_m"]))
        self.assertTrue(result["validation"]["passed"])

    def test_gap_is_respected_without_adding_edge_margin(self):
        analysis = drawing()
        result = nest_pieces(analysis, parameters(analysis, width_mm=210, gap_mm=10), 0.5)
        polygons = []
        for place in result["placements"]:
            polygon = affinity.translate(Polygon(analysis["pieces"][0]["points"]), place["x"], place["y"])
            polygons.append(polygon)
        self.assertGreaterEqual(polygons[0].distance(polygons[1]), 10 - 1e-7)
        self.assertAlmostEqual(result["length_mm"], 50)

    def test_rotation_constraint_is_enforced_when_only_rotated_piece_fits(self):
        analysis = drawing(width=100, height=50)
        config = parameters(analysis, width_mm=60)
        with self.assertRaises(DxfError) as error:
            nest_pieces(analysis, config, 0.5)
        self.assertEqual(error.exception.code, "NEST_TOO_WIDE")
        config["pieces"][0]["rotation_mode"] = "quarter_turn"
        result = nest_pieces(analysis, config, 0.5)
        self.assertTrue(all(p["angle"] in (90, 270) for p in result["placements"]))

    def test_invalid_counts_direction_and_timeout_fail_explicitly(self):
        analysis = drawing()
        for change in [{"set_count": 0}, {"products_per_set": -1}, {"width_mm": float("nan")},
                       {"gap_mm": -1}, {"set_count": 161}]:
            with self.subTest(change=change), self.assertRaises(DxfError):
                nest_pieces(analysis, parameters(analysis, **change), 0.5)
        config = parameters(analysis)
        config["pieces"][0]["rotation_mode"] = "mirror"
        with self.assertRaises(DxfError):
            nest_pieces(analysis, config, 0.5)
        with self.assertRaises(DxfError) as error:
            nest_pieces(analysis, parameters(analysis), 0)
        self.assertEqual(error.exception.code, "NEST_TIMEOUT")

    def test_all_160_instances_are_present_once(self):
        analysis = drawing(width=10, height=10)
        result = nest_pieces(analysis, parameters(analysis, set_count=160), 1)
        self.assertEqual(len(result["placements"]), 160)
        self.assertEqual({p["copy"] for p in result["placements"]}, set(range(160)))
        self.assertTrue(result["validation"]["overlap_free"])

    def test_expanded_vertex_limit_rejects_undownloadable_results(self):
        analysis = drawing()
        points = [[50 + 50 * math.cos(math.tau * i / 1000),
                   50 + 50 * math.sin(math.tau * i / 1000)] for i in range(1000)]
        points.append(points[0])
        analysis["pieces"][0]["points"] = points
        with self.assertRaises(DxfError) as error:
            nest_pieces(analysis, parameters(analysis, set_count=40), 0.1)
        self.assertEqual(error.exception.code, "DXF_COMPLEXITY")

    def test_free_rotation_uses_fifteen_degree_steps_and_preserves_curves(self):
        doc = ezdxf.new(units=4)
        doc.modelspace().add_circle((100, 200), 25)
        analysis = analyze_dxf(dxf_bytes(doc))
        config = parameters(analysis, width_mm=120, gap_mm=2)
        config["pieces"][0]["rotation_mode"] = "free"
        result = nest_pieces(analysis, config, 0.5)
        self.assertEqual(len(result["placements"]), 2)
        self.assertTrue(all(p["angle"] % 15 == 0 for p in result["placements"]))
        exported = ezdxf.read(io.StringIO(export_dxf(analysis, result).decode("ascii")))
        polygons = [Polygon([(v.dxf.location.x, v.dxf.location.y) for v in e.vertices])
                    for e in exported.modelspace()]
        self.assertGreaterEqual(polygons[0].distance(polygons[1]), 2)
        for polygon in polygons:
            self.assertAlmostEqual(polygon.area, 1963.495, delta=0.3)

    def test_coarse_search_envelope_does_not_reject_a_fitting_curve(self):
        doc = ezdxf.new(units=4)
        doc.modelspace().add_circle((0, 0), 50)
        analysis = analyze_dxf(dxf_bytes(doc))
        result = nest_pieces(analysis, parameters(analysis, width_mm=100.01, set_count=1), 0.5)
        self.assertTrue(result["validation"]["bounds_valid"])

    def test_svg_is_one_continuous_frame_and_escapes_uploaded_names(self):
        analysis = drawing()
        config = parameters(analysis)
        config["pieces"][0]["name"] = '<script>alert("x")</script>&'
        result = nest_pieces(analysis, config, 0.5)
        svg = render_svg(analysis, result)
        root = ElementTree.fromstring(svg)
        self.assertEqual(len(root.findall(".//{http://www.w3.org/2000/svg}polygon")), 2)
        self.assertNotIn("<script>", svg)
        self.assertEqual(len(root.findall(".//{http://www.w3.org/2000/svg}rect")), 1)
        content = export_dxf(analysis, result)
        content.decode("ascii")
        exported = ezdxf.read(io.StringIO(content.decode("ascii")))
        outlines = list(exported.modelspace())
        self.assertEqual(len(outlines), 2)
        self.assertTrue(all(e.dxftype() == "POLYLINE" and e.is_closed for e in outlines))
        self.assertTrue(all(len(e.vertices) == 4 for e in outlines))

    def test_svg_replaces_invalid_xml_characters_in_labels(self):
        analysis = drawing()
        config = parameters(analysis)
        config["pieces"][0]["name"] = "座\x00垫\ufffe"
        result = nest_pieces(analysis, config, 0.3)
        self.assertEqual(ElementTree.fromstring(render_svg(analysis, result)).tag,
                         "{http://www.w3.org/2000/svg}svg")

