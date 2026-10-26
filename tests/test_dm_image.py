import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from core.comment_manager import CommentManager


class DMImageTests(unittest.TestCase):
    def _manager(self, asset_path: Path):
        manager = CommentManager.__new__(CommentManager)
        manager.bili = Mock()
        manager.bili.send_private_picture = AsyncMock(return_value=True)
        manager.bili.send_private_message = AsyncMock(return_value=True)
        manager.db = Mock()
        manager.db.get_random_media_asset = Mock(return_value={
            'id': 1, 'path': str(asset_path), 'description': '', 'tags': '',
        })
        manager.db.mark_media_asset_used = Mock()
        manager.db.add_memory_event = Mock()
        return manager

    def test_sends_image_and_caption(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'image.png'
            path.write_bytes(b'png')
            manager = self._manager(path)
            ok = asyncio.run(manager._send_agent_dm_image(
                {'talker_id': 42, 'user': 'viewer', 'content': '在吗'}, '给你看'
            ))
            self.assertTrue(ok)
            manager.bili.send_private_picture.assert_awaited_once_with(42, str(path))
            manager.bili.send_private_message.assert_awaited_once_with(42, '给你看')
            manager.db.mark_media_asset_used.assert_called_once_with(1)

    def test_no_image_in_library(self):
        manager = self._manager(Path('missing.png'))
        manager.db.get_random_media_asset.return_value = None
        self.assertFalse(asyncio.run(manager._send_agent_dm_image({'talker_id': 42}, '')))


if __name__ == '__main__':
    unittest.main()
