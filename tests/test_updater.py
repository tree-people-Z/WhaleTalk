import unittest
from unittest.mock import Mock, patch

from utils import updater


def _release_payload(tag='v1.9.0'):
    return {
        'tag_name': tag,
        'html_url': 'https://github.com/tree-people-Z/WhaleTalk/releases/tag/' + tag,
        'body': 'release notes',
        'assets': [{
            'name': 'WhaleTalk-Windows-x64.zip',
            'browser_download_url': 'https://example.test/WhaleTalk-Windows-x64.zip',
            'size': 123456,
            'digest': 'sha256:abc123',
        }],
    }


class UpdaterTests(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(updater.parse_version('v1.2.3'), (1, 2, 3))
        self.assertEqual(updater.parse_version('1.1'), (1, 1))
        self.assertEqual(updater.parse_version(None), ())

    def test_is_newer_version(self):
        self.assertTrue(updater.is_newer_version('v1.2.0', '1.1.0'))
        self.assertFalse(updater.is_newer_version('v1.1.0', '1.1.0'))
        self.assertFalse(updater.is_newer_version('v1.0.0', '1.1.0'))
        self.assertTrue(updater.is_newer_version('1.1.1', '1.1'))

    def test_check_for_update_returns_downloadable_asset(self):
        response = Mock(status_code=200)
        response.json.return_value = _release_payload('v1.9.1')
        with patch('requests.get', return_value=response):
            result = updater.check_for_update()
        self.assertEqual(result['status'], 'update')
        self.assertEqual(result['version'], '1.9.1')
        self.assertEqual(
            result['asset_url'], 'https://example.test/WhaleTalk-Windows-x64.zip'
        )
        self.assertEqual(result['asset_digest'], 'sha256:abc123')

    def test_check_for_update_reports_latest_version(self):
        response = Mock(status_code=200)
        response.json.return_value = _release_payload('v1.1.0')
        with patch('requests.get', return_value=response):
            result = updater.check_for_update()
        self.assertEqual(result['status'], 'latest')

    def test_check_for_update_reports_network_error(self):
        with patch('requests.get', side_effect=RuntimeError('offline')):
            result = updater.check_for_update()
        self.assertEqual(result['status'], 'error')
        self.assertIn('offline', result['message'])


if __name__ == '__main__':
    unittest.main()
