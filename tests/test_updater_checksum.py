import hashlib
import unittest

from utils.updater import checksum_from_file, is_newer_version, parse_version


class UpdaterChecksumTests(unittest.TestCase):
    def test_parses_sha256sums_line(self):
        digest = hashlib.sha256(b'payload').hexdigest()
        text = (
            '# generated\n'
            f'{digest}  WhaleTalk-Windows-x64.zip\n'
            f'{digest} *WhaleTalk.exe\n'
        )
        self.assertEqual(
            checksum_from_file(text, 'WhaleTalk-Windows-x64.zip'), digest
        )
        self.assertEqual(checksum_from_file(text, 'WhaleTalk.exe'), digest)
        self.assertEqual(checksum_from_file(text, 'missing.zip'), '')

    def test_rejects_malformed_digest(self):
        self.assertEqual(checksum_from_file('not-a-hash  file.zip', 'file.zip'), '')

    def test_version_comparison(self):
        self.assertTrue(is_newer_version('2.3.4', '2.3.3'))
        self.assertFalse(is_newer_version('2.3.3', '2.3.3'))
        self.assertEqual(parse_version('v2.3.3'), (2, 3, 3))


if __name__ == '__main__':
    unittest.main()
