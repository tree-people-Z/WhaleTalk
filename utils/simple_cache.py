"""简单的内存缓存，适用于视频信息等不常变的数据"""
from cachetools import TTLCache
from functools import wraps
from typing import Callable, Any
import asyncio

# 全局缓存实例
_video_cache = TTLCache(maxsize=500, ttl=3600)      # 视频信息缓存1小时
_comment_cache = TTLCache(maxsize=1000, ttl=300)    # 评论缓存5分钟

def cached_video(func: Callable) -> Callable:
    """缓存视频信息的装饰器"""
    @wraps(func)
    async def wrapper(self, bvid: str, *args, **kwargs) -> Any:
        cache_key = f'video:{bvid}'
        
        # 命中缓存
        if cache_key in _video_cache:
            return _video_cache[cache_key]
        
        # 未命中，调用原函数
        result = await func(self, bvid, *args, **kwargs)
        
        # 只缓存非空结果
        if result and isinstance(result, dict):
            _video_cache[cache_key] = result
        
        return result
    return wrapper

def cached_comments(func: Callable) -> Callable:
    """缓存评论列表的装饰器"""
    @wraps(func)
    async def wrapper(self, aid: int, *args, **kwargs) -> Any:
        cache_key = f'comments:{aid}'
        
        if cache_key in _comment_cache:
            return _comment_cache[cache_key]
        
        result = await func(self, aid, *args, **kwargs)
        
        if result and isinstance(result, list):
            _comment_cache[cache_key] = result
        
        return result
    return wrapper

def clear_cache():
    """清空所有缓存（用于测试或手动刷新）"""
    _video_cache.clear()
    _comment_cache.clear()
