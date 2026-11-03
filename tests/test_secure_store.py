import unittest

from utils import secure_store


class SecureStoreTests(unittest.TestCase):
    def test_roundtrip_keeps_plaintext_available(self):
        secret = 'sk-test-中文-123'
        stored = secure_store.protect(secret)
        if secure_store.available():
            self.assertTrue(secure_store.is_encrypted(stored))
            self.assertNotIn('sk-test', stored)
        self.assertEqual(secure_store.unprotect(stored), secret)

    def test_plaintext_and_empty_values_pass_through(self):
        self.assertEqual(secure_store.protect(''), '')
        self.assertEqual(secure_store.unprotect('plain-key'), 'plain-key')
        self.assertEqual(secure_store.unprotect(''), '')

    def test_double_protect_is_idempotent(self):
        once = secure_store.protect('secret')
        self.assertEqual(secure_store.protect(once), once)

    def test_corrupted_ciphertext_returns_empty(self):
        if not secure_store.available():
            self.skipTest('DPAPI only on Windows')
        self.assertEqual(
            secure_store.unprotect(secure_store.PREFIX + 'AAAA'), ''
        )


if __name__ == '__main__':
    unittest.main()
