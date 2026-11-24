"""DXF 提取用真实内存 DXF 验证，不连接数据库或写源文件。"""

import io
import unittest

import ezdxf

from codex_runtime.dxf_tools.dxf_geometry import DxfError, analyze_dxf


def dxf_bytes(document):
    stream = io.StringIO()
    document.write(stream)
    return stream.getvalue().encode(document.output_encoding)


def rectangle(layout, x=0, y=0, width=100, height=50):
    return layout.add_lwpolyline(
        [(x, y), (x + width, y), (x + width, y + height), (x, y + height)],
        close=True,
    )


class DxfGeometryTests(unittest.TestCase):
    def test_chinese_text_quantity_and_dimensions_are_not_pieces(self):
        doc = ezdxf.new("R2004", units=4)
        doc.encoding = "gbk"
        rectangle(doc.modelspace())
        doc.modelspace().add_mtext("坐垫*2", dxfattribs={"insert": (30, 25)})
        doc.modelspace().add_linear_dim(base=(0, -10), p1=(0, 0), p2=(100, 0)).render()
        result = analyze_dxf(dxf_bytes(doc))
        self.assertEqual(len(result["pieces"]), 1)
        self.assertEqual(result["pieces"][0]["name"], "坐垫")
        self.assertEqual(result["pieces"][0]["quantity"], 2)
        self.assertAlmostEqual(result["pieces"][0]["area_mm2"], 5000)

    def test_unordered_reversed_lines_are_joined_without_region_rules(self):
        doc = ezdxf.new(units=4)
        for start, end in [((100, 50), (100, 0)), ((0, 0), (100, 0)),
                           ((0, 50), (0, 0)), ((100, 50), (0, 50))]:
            doc.modelspace().add_line(start, end)
        result = analyze_dxf(dxf_bytes(doc))
        self.assertEqual(len(result["pieces"]), 1)
        self.assertAlmostEqual(result["pieces"][0]["area_mm2"], 5000)

    def test_insert_transform_preserves_displayed_dimensions(self):
        doc = ezdxf.new(units=4)
        block = doc.blocks.new("PART")
        rectangle(block, width=10, height=20)
        doc.modelspace().add_blockref("PART", (300, 900), dxfattribs={
            "xscale": 2, "yscale": 2, "zscale": 2, "rotation": 90,
        })
        result = analyze_dxf(dxf_bytes(doc))["pieces"][0]
        self.assertAlmostEqual(result["width_mm"], 40)
        self.assertAlmostEqual(result["height_mm"], 20)
        self.assertAlmostEqual(result["area_mm2"], 800)

    def test_planar_insert_can_leave_z_scale_at_default(self):
        doc = ezdxf.new(units=4)
        rectangle(doc.blocks.new("PART"), width=10, height=20)
        doc.modelspace().add_blockref("PART", (0, 0), dxfattribs={"xscale": 2, "yscale": 2})
        result = analyze_dxf(dxf_bytes(doc))["pieces"][0]
        self.assertAlmostEqual(result["area_mm2"], 800)

    def test_nested_and_multiple_insert_keep_all_instances(self):
        doc = ezdxf.new(units=4)
        rectangle(doc.blocks.new("PART"), width=10, height=20)
        container = doc.blocks.new("CONTAINER")
        container.add_blockref("PART", (5, 5))
        doc.modelspace().add_blockref("CONTAINER", (10, 10), dxfattribs={
            "column_count": 3, "column_spacing": 50,
        })
        pieces = analyze_dxf(dxf_bytes(doc))["pieces"]
        self.assertEqual(len(pieces), 3)
        self.assertTrue(all(abs(piece["area_mm2"] - 200) < 1e-8 for piece in pieces))

    def test_internal_nested_outline_is_rejected_instead_of_counted_twice(self):
        doc = ezdxf.new(units=4)
        rectangle(doc.modelspace())
        rectangle(doc.modelspace(), x=10, y=10, width=10, height=10)
        with self.assertRaises(DxfError) as error:
            analyze_dxf(dxf_bytes(doc))
        self.assertEqual(error.exception.code, "DXF_AMBIGUOUS_CONTOUR")

    def test_unknown_units_require_explicit_override(self):
        doc = ezdxf.new(units=0)
        rectangle(doc.modelspace(), width=10, height=20)
        with self.assertRaises(DxfError) as error:
            analyze_dxf(dxf_bytes(doc))
        self.assertEqual(error.exception.code, "DXF_UNIT_UNKNOWN")
        piece = analyze_dxf(dxf_bytes(doc), "cm")["pieces"][0]
        self.assertEqual(piece["width_mm"], 100)
        self.assertEqual(piece["height_mm"], 200)

    def test_open_self_intersecting_and_branched_contours_are_rejected(self):
        for coordinates, closed in [([(0, 0), (10, 0), (10, 10)], False),
                                    ([(0, 0), (10, 10), (0, 10), (10, 0)], True)]:
            with self.subTest(coordinates=coordinates):
                doc = ezdxf.new(units=4)
                doc.modelspace().add_lwpolyline(coordinates, close=closed)
                with self.assertRaises(DxfError):
                    analyze_dxf(dxf_bytes(doc))
        doc = ezdxf.new(units=4)
        rectangle(doc.modelspace())
        doc.modelspace().add_line((0, 0), (-10, 0))
        with self.assertRaises(DxfError):
            analyze_dxf(dxf_bytes(doc))

    def test_nonuniform_insert_and_3d_geometry_are_rejected(self):
        doc = ezdxf.new(units=4)
        rectangle(doc.blocks.new("PART"))
        doc.modelspace().add_blockref("PART", (0, 0), dxfattribs={"xscale": 2})
        with self.assertRaises(DxfError) as error:
            analyze_dxf(dxf_bytes(doc))
        self.assertEqual(error.exception.code, "DXF_UNSUPPORTED")
        doc = ezdxf.new(units=4)
        doc.modelspace().add_line((0, 0, 1), (20, 30, 2))
        with self.assertRaises(DxfError):
            analyze_dxf(dxf_bytes(doc))

    def test_circle_and_two_vertex_bulge_are_not_degenerate(self):
        doc = ezdxf.new(units=4)
        doc.modelspace().add_circle((0, 0), 10)
        doc.modelspace().add_lwpolyline([(40, 0, 1), (60, 0, 1)], format="xyb", close=True)
        pieces = analyze_dxf(dxf_bytes(doc))["pieces"]
        self.assertEqual(len(pieces), 2)
        for piece in pieces:
            self.assertAlmostEqual(piece["width_mm"], 20, places=2)
            self.assertGreater(piece["area_mm2"], 314)

    def test_full_turn_arc_is_retained_when_other_pieces_exist(self):
        doc = ezdxf.new(units=4)
        rectangle(doc.modelspace())
        doc.modelspace().add_arc((200, 0), 10, start_angle=0, end_angle=360)
        pieces = analyze_dxf(dxf_bytes(doc))["pieces"]
        self.assertEqual(len(pieces), 2)
        self.assertGreater(pieces[1]["area_mm2"], 314)

    def test_legacy_polyline_default_width_is_rejected(self):
        doc = ezdxf.new(units=4)
        doc.modelspace().add_polyline2d(
            [(0, 0), (100, 0), (100, 50), (0, 50)], close=True,
            dxfattribs={"default_start_width": 5, "default_end_width": 5},
        )
        with self.assertRaises(DxfError) as error:
            analyze_dxf(dxf_bytes(doc))
        self.assertEqual(error.exception.code, "DXF_UNSUPPORTED")

    def test_binary_and_malformed_files_are_rejected(self):
        for value in [b"AutoCAD Binary DXF\r\n\x1a\0", b"not a drawing", b""]:
            with self.subTest(value=value), self.assertRaises(DxfError):
                analyze_dxf(value)

    def test_windows_newlines_preserve_binary_tags_in_text_dxf(self):
        doc = ezdxf.new(units=4)
        rectangle(doc.modelspace())
        doc.appids.new("BINARY_NOTE")
        list(doc.modelspace())[0].set_xdata("BINARY_NOTE", [(1004, b"\x01\x02\x03")])
        source = dxf_bytes(doc).replace(b"\n", b"\r\n")
        self.assertEqual(len(analyze_dxf(source)["pieces"]), 1)

