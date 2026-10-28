"""缓存功能测试"""
import unittest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from utils.simple_cache import cached_video, clear_cache


class SimpleCacheTests(unittest.TestCase):
    def test_cache_decorator_caches_results(self):
        """测试缓存装饰器缓存结果"""
        clear_cache()
        
        # 创建一个带缓存的异步函数
        call_count = [0]
        
        @cached_video
        async def fetch_video(self, bvid):
            call_count[0] += 1
            return {'bvid': bvid, 'title': f'Video {bvid}'}
        
        # 创建mock对象
        obj = Mock()
        
        # 第一次调用
        result1 = asyncio.run(fetch_video(obj, 'BV1test'))
        self.assertEqual(result1['bvid'], 'BV1test')
        self.assertEqual(call_count[0], 1)
        
        # 第二次调用应该命中缓存
        result2 = asyncio.run(fetch_video(obj, 'BV1test'))
        self.assertEqual(result2['bvid'], 'BV1test')
        self.assertEqual(call_count[0], 1)  # 没有增加
        
        # 不同bvid不应该命中缓存
        result3 = asyncio.run(fetch_video(obj, 'BV1other'))
        self.assertEqual(result3['bvid'], 'BV1other')
        self.assertEqual(call_count[0], 2)  # 增加了
    
    def test_clear_cache_works(self):
        """测试清空缓存功能"""
        clear_cache()
        
        call_count = [0]
        
        @cached_video
        async def fetch_video(self, bvid):
            call_count[0] += 1
            return {'bvid': bvid}
        
        obj = Mock()
        
        # 第一次调用
        asyncio.run(fetch_video(obj, 'BV1test'))
        self.assertEqual(call_count[0], 1)
        
        # 第二次调用命中缓存
        asyncio.run(fetch_video(obj, 'BV1test'))
        self.assertEqual(call_count[0], 1)
        
        # 清空缓存
        clear_cache()
        
        # 再次调用不命中缓存
        asyncio.run(fetch_video(obj, 'BV1test'))
        self.assertEqual(call_count[0], 2)


if __name__ == '__main__':
    unittest.main()
