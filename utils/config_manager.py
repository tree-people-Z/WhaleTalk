"""
配置管理模块
"""

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from loguru import logger

from utils import secure_store


class ConfigManager:
    """配置管理器"""

    # 需要加密落盘的配置项（内存里始终是明文）。
    _SECRET_KEYS = (
        'ai.api_key',
        'analysis.cloud_transcription.api_key',
    )

    def __init__(self, config_path: Optional[Path] = None):
        """
        初始化配置管理器

        Args:
            config_path: 配置文件路径
        """
        self.config_path = config_path or Path("data/config.json")
        self.config: Dict[str, Any] = {}
        self._batch_depth = 0
        self._dirty = False
        self.load()

    def load(self):
        """加载配置"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                self._migrate_legacy()
                self._merge_defaults()
                self._normalize_secrets()
                needs_migration = self._decrypt_secrets()
                self._normalize_transcription()
                if needs_migration:
                    # 把遗留的明文 API Key 立即转成密文
                    self.save()
                    logger.info("已将明文密钥迁移为加密存储")
                logger.info(f"配置已加载: {self.config_path}")
            except Exception as e:
                logger.error(f"加载配置失败: {e}")
                self.config = self.get_default_config()
        else:
            logger.info("配置文件不存在，使用默认配置")
            self.config = self.get_default_config()

    def _migrate_legacy(self):
        """Migrate old keys before defaults fill in the new keys."""
        interaction = self.config.get('interaction')
        if not isinstance(interaction, dict):
            return
        if 'reply_scope' not in interaction and interaction.get('reply_only_owner') is True:
            interaction['reply_scope'] = 'owner'

    def _merge_defaults(self):
        """把新增默认配置项补进旧配置文件，避免设置缺失。"""
        defaults = self.get_default_config()
        if self._merge_missing(self.config, defaults):
            logger.info("配置已补充新增默认项")
            self.save()

    @classmethod
    def _merge_missing(cls, target: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
        changed = False
        for key, value in defaults.items():
            if key not in target:
                target[key] = value
                changed = True
            elif isinstance(value, dict) and isinstance(target.get(key), dict):
                changed = cls._merge_missing(target[key], value) or changed
        return changed

    def save(self):
        """保存配置（敏感项加密落盘）。"""
        try:
            self._normalize_secrets()
            self._normalize_transcription()
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            payload = self._encrypted_copy(self.config)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            logger.info("配置已保存")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    @classmethod
    def _get_path(cls, config: Dict[str, Any], dotted: str) -> Any:
        value: Any = config
        for key in dotted.split('.'):
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        return value

    @classmethod
    def _set_path(cls, config: Dict[str, Any], dotted: str, value: Any) -> None:
        keys = dotted.split('.')
        target = config
        for key in keys[:-1]:
            node = target.get(key)
            if not isinstance(node, dict):
                node = {}
                target[key] = node
            target = node
        target[keys[-1]] = value

    def _encrypted_copy(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """返回加密后的深拷贝，避免把密文写回内存中的配置。"""
        import copy

        payload = copy.deepcopy(config)
        for dotted in self._SECRET_KEYS:
            value = self._get_path(payload, dotted)
            if isinstance(value, str) and value:
                self._set_path(payload, dotted, secure_store.protect(value))
        return payload

    def _decrypt_secrets(self) -> bool:
        """读盘后把密文解回明文，供运行时使用。

        Returns:
            是否存在需要迁移的明文密钥。
        """
        needs_migration = False
        for dotted in self._SECRET_KEYS:
            value = self._get_path(self.config, dotted)
            if not isinstance(value, str) or not value:
                continue
            if secure_store.is_encrypted(value):
                self._set_path(
                    self.config, dotted, secure_store.unprotect(value)
                )
            elif secure_store.available():
                needs_migration = True
        return needs_migration

    @contextmanager
    def batch(self) -> Iterator['ConfigManager']:
        """批量修改配置：中间不写盘，退出时只保存一次。"""
        self._batch_depth += 1
        try:
            yield self
        finally:
            self._batch_depth -= 1
            if self._batch_depth == 0 and self._dirty:
                self._dirty = False
                self.save()

    def _normalize_transcription(self):
        """本地转写只提供 medium 模型；transcription_mode 控制关闭/本地/云端。"""
        analysis = self.config.get('analysis')
        if not isinstance(analysis, dict):
            return
        mode = analysis.get('transcription_mode')
        if mode not in ('off', 'local', 'cloud'):
            mode = 'local' if analysis.get('local_transcription_enabled') else 'off'
        analysis['transcription_mode'] = mode
        analysis['local_transcription_enabled'] = mode == 'local'
        analysis.setdefault('local_transcription_model', 'medium')
        analysis.setdefault('local_model_idle_unload_minutes', 10)
        cloud = analysis.get('cloud_transcription')
        if not isinstance(cloud, dict):
            cloud = {}
        cloud.setdefault('base_url', 'https://api.openai.com/v1')
        cloud.setdefault('api_key', '')
        cloud.setdefault('model', 'whisper-1')
        analysis['cloud_transcription'] = cloud

    def _normalize_secrets(self):
        """清除密钥首尾空白，避免换行破坏 HTTP 请求头。"""
        ai_config = self.config.get('ai')
        if isinstance(ai_config, dict) and isinstance(ai_config.get('api_key'), str):
            ai_config['api_key'] = ai_config['api_key'].strip()

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        keys = key.split('.')
        value = self.config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value

    def set(self, key: str, value: Any):
        """设置配置项"""
        keys = key.split('.')
        config = self.config

        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        config[keys[-1]] = value
        if self._batch_depth > 0:
            self._dirty = True
        else:
            self.save()

    def get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            "bilibili": {
                "owner_uid": "",
                "owner_name": ""
            },
            "ai": {
                "provider": "deepseek",
                "api_key": "",
                "model": "deepseek-flash",
                "base_url": "https://api.deepseek.com",
                "timeout_seconds": 60,
                "max_retries": 2,
                "max_output_tokens": 8000,
                "vision_timeout_seconds": 20
            },
            "persona": {
                "name": "鲸鱼娘",
                "persona_file": "data/persona.md",
                "enabled": True
            },
            "schedule": {
                "auto_run": False,
                "wake_windows": [
                    [12, 14],  # 中午12-14点
                    [18, 21]   # 晚上18-21点
                ],
                "browse_interval_min_minutes": 5,
                "browse_interval_max_minutes": 30,
                "reply_check_interval_minutes": 1,
                "deepseek_offpeak_only": True,
                "deepseek_offpeak_windows": "00:00-09:00,12:00-14:00,18:00-24:00"
            },
            "search": {
                "keywords": [
                    "DeepSeek娘",
                    "鲸鱼娘",
                    "ai娘",
                    "大肥鱼",
                    "二次元"
                ],
                "max_results_per_keyword": 5,
                "order": "totalrank"  # 综合排序
            },
            "limits": {
                "max_comments_per_day": 60,
                "max_writes_per_round": 8,
                "max_likes_per_day": 50,
                "max_dm_per_check": 3,
                "max_dm_per_day": 10,
                "max_videos_per_run": 20,
                "skip_analyzed_within_hours": 2,
                "same_video_cooldown_days": 7,
                "min_score_to_comment": 10,
                "min_score_to_mention_owner": 13
            },
            "interaction": {
                "auto_comment": True,
                "auto_like_commented_video": False,
                "like_replied_comments": True,
                "favorite_commented_video": True,
                "follow_commented_up": False,
                "like_up_dynamics": False,
                "post_video_dynamic": False,
                "prob_like_reply": 50,
                "prob_report_watch": 50,
                "prob_favorite_video": 20,
                "prob_follow_up": 10,
                "prob_like_dynamic": 10,
                "prob_post_dynamic": 5,
                "prob_coin_video": 5,
                "prob_share_video": 2,
                "prob_watch_later": 10,
                "prob_repost_dynamic": 3,
                "reply_private_messages": True,
                "coin_commented_video": True,
                "share_commented_video": False,
                "watch_later_commented_video": True,
                "repost_up_dynamic": False,
                "send_danmaku": False,
                "like_danmaku": False,
                "prob_send_danmaku": 2,
                "prob_like_danmaku": 5,
                "report_watching": False,
                "comment_monitor": True,
                "auto_reply": True,
                "reply_scope": "all",
                "own_video_count": 10,
                "max_own_video_replies_per_check": 10,
                "max_new_comments_per_check": 30,
                "mention_owner_on_interesting": False
            },
            "diaries": {
                "auto_compact": True,
                "compact_after_days": 3,
                "compact_min_chars": 1200,
                "keep_backups": 3
            },
            "evolution": {
                "enabled": True,
                "learn_interval_hours": 12,
                "anti_repetition": True,
                "max_items": 60,
                "max_context_chars": 2400
            },
            "analysis": {
                "enable_frame_analysis": True,
                "transcription_mode": "off",
                "local_transcription_enabled": False,
                "local_transcription_model": "medium",
                "local_model_idle_unload_minutes": 10,
                "cloud_transcription": {
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "",
                    "model": "whisper-1"
                }
            }
        }

    def create_default_config(self):
        """创建默认配置文件"""
        self.config = self.get_default_config()
        self.save()
        logger.info("已创建默认配置文件")

    @property
    def config_file(self) -> Path:
        """配置文件路径"""
        return self.config_path
