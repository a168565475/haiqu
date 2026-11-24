import io
import stat
import zipfile

from django.test import SimpleTestCase
from ..preprocessing import ManifestError, parse_xml, resolve_part, validate_package


class SourceBoundaryTests(SimpleTestCase):
    def package(self, entries):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            for name, data in entries:
                archive.writestr(name, data)
        return zipfile.ZipFile(io.BytesIO(output.getvalue()))

    def test_zip_traversal_and_case_duplicates_rejected(self):
        for entries in ([('../outside.txt', b'x')], [('A.xml', b'x'), ('a.xml', b'y')]):
            with self.subTest(entries=entries), self.package(entries) as archive:
                with self.assertRaises(ManifestError):
                    validate_package(archive)

    def test_symlink_rejected(self):
        info = zipfile.ZipInfo('link')
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.package([(info, b'/etc/passwd')]) as archive:
            with self.assertRaises(ManifestError):
                validate_package(archive)

    def test_encoded_xml_dtd_rejected(self):
        data = '<?xml version="1.0" encoding="utf-16"?><!DOCTYPE a [<!ENTITY e "secret">]><a>&e;</a>'.encode('utf-16')
        with self.assertRaises(ManifestError):
            parse_xml(data)

    def test_external_and_escaping_relationship_rejected(self):
        for target in ['https://example.com/file', '../../../../../outside', '..\\secret', '%00x']:
            with self.subTest(target=target), self.assertRaises(ManifestError):
                resolve_part('xl/worksheets/sheet1.xml', target)
        self.assertEqual(resolve_part('xl/worksheets/sheet1.xml', '../drawings/drawing1.xml'), 'xl/drawings/drawing1.xml')
