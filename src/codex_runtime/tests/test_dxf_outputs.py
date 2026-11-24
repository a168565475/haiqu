import unittest
from unittest.mock import MagicMock, patch

from codex_runtime.dxf_tools.dxf_geometry import DxfError
from codex_runtime.dxf_tools.runner import MAX_BYTES, render_outputs


class DxfOutputTests(unittest.TestCase):
    @staticmethod
    def sized_output(size):
        value = MagicMock()
        value.__len__.return_value = size
        return value

    def test_oversized_svg_is_rejected_before_dxf_rendering(self):
        svg = MagicMock()
        svg.encode.return_value = self.sized_output(MAX_BYTES + 1)
        with patch('codex_runtime.dxf_tools.dxf_rendering.render_svg', return_value=svg), \
                patch('codex_runtime.dxf_tools.dxf_rendering.export_dxf') as export:
            with self.assertRaises(DxfError) as error:
                list(render_outputs({}, {}))
        self.assertEqual(error.exception.code, 'RESULT_LIMIT')
        export.assert_not_called()

    def test_oversized_dxf_is_rejected_after_svg_succeeds(self):
        with patch('codex_runtime.dxf_tools.dxf_rendering.render_svg', return_value='<svg/>'), \
                patch('codex_runtime.dxf_tools.dxf_rendering.export_dxf', return_value=self.sized_output(MAX_BYTES + 1)):
            with self.assertRaises(DxfError) as error:
                list(render_outputs({}, {}))
        self.assertEqual(error.exception.code, 'RESULT_LIMIT')

    def test_exact_output_limit_is_accepted(self):
        svg = MagicMock()
        svg.encode.return_value = self.sized_output(MAX_BYTES)
        with patch('codex_runtime.dxf_tools.dxf_rendering.render_svg', return_value=svg), \
                patch('codex_runtime.dxf_tools.dxf_rendering.export_dxf', return_value=self.sized_output(MAX_BYTES)):
            self.assertEqual(len(list(render_outputs({}, {}))), 2)

    def test_unknown_rendering_error_is_not_swallowed(self):
        with patch('codex_runtime.dxf_tools.dxf_rendering.render_svg', side_effect=RuntimeError('rendering bug')):
            with self.assertRaisesRegex(RuntimeError, 'rendering bug'):
                list(render_outputs({}, {}))
