from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.exceptions import ValidationError

from apps.boms.uploads import prepare_bom_upload, persist_prepared_bom_upload
from apps.files.models import FileScanStatus
from apps.files.uploads import save_scanned_document, save_scanned_image
from apps.imports.security import InfectedFile, ScannerUnavailable, save_and_scan_upload, scan_upload
from apps.inquiries.uploads import save_inquiry_attachment
from apps.quotations.uploads import save_quotation_formal_document
from apps.samples.uploads import save_payment_evidence, save_sample_parameter_file


class UploadScanPolicyTests(SimpleTestCase):
    def test_enabled_scanner_success_returns_clean(self):
        scanner = Mock(return_value="stream: OK")
        with override_settings(FILE_VIRUS_SCAN_ENABLED=True):
            status, message = scan_upload(Path("/tmp/upload"), scanner=scanner)
        self.assertEqual(status, FileScanStatus.CLEAN)
        self.assertEqual(message, "stream: OK")
        scanner.assert_called_once()

    def test_disabled_scanner_returns_skipped_without_calling_scanner(self):
        scanner = Mock(side_effect=ScannerUnavailable())
        with override_settings(FILE_VIRUS_SCAN_ENABLED=False):
            status, message = scan_upload(Path("/tmp/upload"), scanner=scanner)
        self.assertEqual(status, FileScanStatus.SKIPPED)
        self.assertIn("未执行病毒扫描", message)
        scanner.assert_not_called()

    def test_enabled_scanner_errors_are_preserved(self):
        for error in (ScannerUnavailable(), InfectedFile()):
            with self.subTest(error=type(error).__name__), override_settings(FILE_VIRUS_SCAN_ENABLED=True):
                with self.assertRaises(type(error)):
                    scan_upload(Path("/tmp/upload"), scanner=Mock(side_effect=error))


class GenericUploadScanPolicyTests(TestCase):
    @override_settings(FILE_VIRUS_SCAN_ENABLED=False)
    def test_image_upload_is_skipped_and_file_is_readable(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            uploaded = SimpleUploadedFile("photo.png", b"\x89PNG\r\n\x1a\nvalid", content_type="image/png")
            business_file = save_scanned_image(
                uploaded,
                None,
                storage_folder="tests/images",
                field_label="测试图片",
            )
            self.assertEqual(business_file.scan_status, FileScanStatus.SKIPPED)
            self.assertIsNone(business_file.scanned_at)
            self.assertTrue((Path(directory) / business_file.storage_key).is_file())

    @override_settings(FILE_VIRUS_SCAN_ENABLED=False)
    def test_disabled_scan_keeps_signature_size_and_extension_validation(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            with patch("apps.files.uploads._clamav_scan") as scanner:
                for name, content in (("fake.png", b"invalid"), ("empty.png", b""), ("program.exe", b"program")):
                    with self.subTest(name=name), self.assertRaises(ValidationError):
                        save_scanned_image(SimpleUploadedFile(name, content), None, storage_folder="tests", field_label="图片")
                with self.assertRaises(ValidationError):
                    save_scanned_image(SimpleUploadedFile("large.png", b"\x89PNG\r\n\x1a\n"), None, storage_folder="tests", field_label="图片", max_bytes=4)
                scanner.assert_not_called()
            self.assertEqual([path for path in Path(directory).rglob("*") if path.is_file()], [])

    @override_settings(FILE_VIRUS_SCAN_ENABLED=False)
    def test_document_upload_is_skipped_and_file_is_readable(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            uploaded = SimpleUploadedFile("proof.pdf", b"%PDF-1.7 test", content_type="application/pdf")
            business_file = save_scanned_document(
                uploaded,
                None,
                storage_folder="tests/documents",
                field_label="测试文件",
            )
            self.assertEqual(business_file.scan_status, FileScanStatus.SKIPPED)
            self.assertIsNone(business_file.scanned_at)
            self.assertTrue((Path(directory) / business_file.storage_key).is_file())


class CustomUploadScanPolicyTests(TestCase):
    def upload_cases(self):
        return [
            ("inquiry", "apps.inquiries.uploads._clamav_scan", lambda: save_inquiry_attachment(SimpleUploadedFile("attachment.pdf", b"%PDF-1.7 test"), None, uuid4(), uuid4())),
            ("quotation", "apps.quotations.uploads._clamav_scan", lambda: save_quotation_formal_document(SimpleUploadedFile("quotation.pdf", b"%PDF-1.7 test"), None)),
            ("payment", "apps.samples.uploads._clamav_scan", lambda: save_payment_evidence(SimpleUploadedFile("payment.pdf", b"%PDF-1.7 test"), None)),
            ("parameter", "apps.samples.uploads._clamav_scan", lambda: save_sample_parameter_file(SimpleUploadedFile("parameter.pdf", b"%PDF-1.7 test"), None, parameter_type="metalwork")),
            ("contact", "apps.imports.security._clamav_scan", lambda: save_and_scan_upload(SimpleUploadedFile("contacts.csv", b"name,email\nTest,test@example.com"), None)[0]),
            ("bom", "apps.boms.uploads._clamav_scan", lambda: persist_prepared_bom_upload(prepare_bom_upload(SimpleUploadedFile("bom.xlsx", b"PK\x03\x04test")), None)[0]),
        ]

    @override_settings(FILE_VIRUS_SCAN_ENABLED=False)
    def test_all_custom_uploads_skip_unavailable_scanner_and_preserve_files(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            for name, target, save in self.upload_cases():
                with self.subTest(upload=name), patch(target, side_effect=ScannerUnavailable()) as scanner:
                    business_file = save()
                    scanner.assert_not_called()
                    self.assertEqual(business_file.scan_status, FileScanStatus.SKIPPED)
                    self.assertIsNone(business_file.scanned_at)
                    self.assertTrue((Path(directory) / business_file.storage_key).is_file())

    @override_settings(FILE_VIRUS_SCAN_ENABLED=True)
    def test_all_custom_uploads_scan_when_reenabled(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            for name, target, save in self.upload_cases():
                with self.subTest(upload=name), patch(target, return_value="stream: OK") as scanner:
                    business_file = save()
                    scanner.assert_called_once()
                    self.assertEqual(business_file.scan_status, FileScanStatus.CLEAN)
                    self.assertIsNotNone(business_file.scanned_at)

    @override_settings(FILE_VIRUS_SCAN_ENABLED=True)
    def test_bom_scanner_failure_cleans_temporary_file(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            for error in (ScannerUnavailable(), InfectedFile()):
                with self.subTest(error=type(error).__name__):
                    with patch("apps.boms.uploads._clamav_scan", side_effect=error) as scanner, self.assertRaises(type(error)):
                        prepare_bom_upload(SimpleUploadedFile("bom.xlsx", b"PK\x03\x04test"))
                    scanner.assert_called_once()
                    temporary_path = scanner.call_args.args[0]
                    self.assertFalse(temporary_path.exists())
                    self.assertFalse(temporary_path.parent.exists())
