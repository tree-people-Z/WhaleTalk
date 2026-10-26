import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.bilibili_api import BilibiliAPI
from gui.comments_tab import CommentsTab, ThreadLoadWorker


class CommentImageTests(unittest.TestCase):
    def test_extracts_single_and_multi_images(self):
        content = {
            'picture': '//i0.hdslb.com/a.jpg',
            'pictures': [
                {'img_src': '//i0.hdslb.com/b.png'},
                'https://i0.hdslb.com/c.webp',
            ],
        }
        self.assertEqual(BilibiliAPI._extract_comment_images(content), [
            'https://i0.hdslb.com/b.png',
            'https://i0.hdslb.com/c.webp',
            'https://i0.hdslb.com/a.jpg',
        ])

    def test_cache_images_downloads_to_local_cache(self):
        image_bytes = b'\x89PNG\r\n\x1a\n' + b'0' * 32
        response = Mock()
        response.ok = True
        response.content = image_bytes
        response.headers = {'Content-Type': 'image/png'}

        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as directory, \
                patch('gui.comments_tab.requests.get', return_value=response):
            os.chdir(directory)
            try:
                replies = [{
                    'rpid': 1,
                    'images': ['https://i0.hdslb.com/comment.png'],
                }]
                ThreadLoadWorker._cache_images(replies)
                local = replies[0]['local_images']
                self.assertEqual(len(local), 1)
                self.assertTrue(Path(local[0]).is_file())
                page = CommentsTab._images_html(replies[0])
                self.assertIn('<img src="file:///', page)
            finally:
                os.chdir(old_cwd)


if __name__ == '__main__':
    unittest.main()
