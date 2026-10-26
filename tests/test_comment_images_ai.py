import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import comment_images


class FakeAI:
    async def describe_image(self, path):
        return '图里是一只猫'


class CommentImageRecognitionTests(unittest.TestCase):
    def test_attaches_description_and_caches(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'x.jpg'
            image.write_bytes(b'jpg')
            comments = [{'images': ['https://example.com/a.jpg']}]
            with patch.object(comment_images, '_download', return_value=image):
                result = asyncio.run(
                    comment_images.describe_comment_images(comments, FakeAI())
                )
            self.assertEqual(result[0]['image_descriptions'], ['图里是一只猫'])

    def test_without_ai_leaves_comments_unchanged(self):
        comments = [{'images': ['https://example.com/a.jpg']}]
        result = asyncio.run(
            comment_images.describe_comment_images(comments, None)
        )
        self.assertEqual(result[0], {'images': ['https://example.com/a.jpg']})


if __name__ == '__main__':
    unittest.main()
