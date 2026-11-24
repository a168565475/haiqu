from cryptography.fernet import Fernet
from django.test import SimpleTestCase, override_settings
from rest_framework.exceptions import APIException

from ..crypto import decrypt_key, encrypt_key, key_metadata


class OpenAIKeyCryptoTests(SimpleTestCase):
    def test_round_trip_and_metadata_do_not_expose_plaintext(self):
        key = Fernet.generate_key().decode("ascii")
        with override_settings(OPENAI_FERNET_KEYS=[key]):
            ciphertext = encrypt_key("sk-test-secret-value")
            self.assertNotEqual(ciphertext, "sk-test-secret-value")
            self.assertEqual(decrypt_key(ciphertext), "sk-test-secret-value")
            last4, fingerprint = key_metadata("sk-test-secret-value")
            self.assertEqual(last4, "alue")
            self.assertEqual(len(fingerprint), 64)

    def test_missing_encryption_key_fails_closed(self):
        with override_settings(OPENAI_FERNET_KEYS=[]):
            with self.assertRaises(APIException):
                encrypt_key("sk-test-secret-value")

