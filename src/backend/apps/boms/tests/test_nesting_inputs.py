import json
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.boms.api.nesting_serializers import NestingUploadSerializer


class NestingInputTests(SimpleTestCase):
    def serializer(self, snapshot):
        return NestingUploadSerializer(data={
            "file": SimpleUploadedFile("piece.dxf", b"0\nEOF\n"),
            "draft_key": str(uuid4()), "target_snapshot": snapshot,
        })

    def test_nonfinite_multipart_json_returns_field_error_with_status_400(self):
        # Python json.loads 接受这些常量；模拟 multipart JSON 字段进入 Serializer。
        for literal in ["NaN", "Infinity", "-Infinity"]:
            with self.subTest(literal=literal):
                serializer = self.serializer(json.loads('{"unit":"米","x":' + literal + '}'))
                with self.assertRaises(ValidationError) as caught:
                    serializer.is_valid(raise_exception=True)
                self.assertEqual(caught.exception.status_code, 400)
                self.assertIn("target_snapshot", caught.exception.detail)

    def test_nonserializable_snapshot_is_a_field_error_not_internal_error(self):
        serializer = self.serializer({"unit": "米", "x": object()})
        self.assertFalse(serializer.is_valid())
        self.assertIn("target_snapshot", serializer.errors)

    def test_finite_snapshot_remains_valid(self):
        serializer = self.serializer({"unit": "米", "width": 1500.5})
        self.assertTrue(serializer.is_valid(), serializer.errors)
