"""
配置管理模块
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional
from loguru import logger


class ConfigManager:
    """配置管理器"""

    def __init__(self, config_path: Optional[Path] = None):
        """
        初始化配置管理器

        Args:
            config_path: 配置文件路径
        """
        self.config_path = config_path or Path("data/config.json")
        self.config: Dict[str, Any] = {}
        self.load()

    def load(self):
        """加载配置"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                self._merge_defaults()
                self._normalize_secrets()
                self._normalize_transcription()
                logger.info(f"配置已加载: {self.config_path}")
            except Exception as e:
                logger.error(f"加载配置失败: {e}")
                self.config = self.get_default_config()
        else:
            logger.info("配置文件不存在，使用默认配置")
            self.config = self.get_default_config()

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
        """保存配置"""
        try:
            self._normalize_secrets()
            self._normalize_transcription()
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            logger.info("配置已保存")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

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
        analysis['local_transcription_model'] = 'medium'
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
        self.save()

    def get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            "bilibili": {
                "owner_uid": "",
                "owner_name": "",
                "credential_path": "data/cookies.json"
            },
            "ai": {
                "provider": "deepseek",
                "api_key": "",
                "model": "deepseek-flash",
                "base_url": "https://api.deepseek.com"
            },
            "persona": {
                "name": "鲸鱼娘",
                "self_reference": "我",
                "user_reference": "主人",
                "persona_file": "data/persona.md",
                "enabled": True
            },
            "schedule": {
                "auto_run": False,
                "wake_windows": [
                    [12, 14],  # 中午12-14点
                    [18, 21]   # 晚上18-21点
                ],
                "wake_probability": 0.7,
                "random_delay_minutes": 30,
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
                "max_likes_per_day": 50,
                "max_videos_per_run": 20,
                "skip_analyzed_within_hours": 2,
                "max_greetings_per_video": 2,
                "max_greetings_per_run": 5,
                "max_interactions_per_video": 1,
                "max_interactions_per_run": 3,
                "same_video_cooldown_days": 7,
                "min_score_to_comment": 10,
                "min_score_to_mention_owner": 13,
                "mention_owner_on_interesting": False
            },
            "interaction": {
                "auto_comment": True,
                "auto_like_commented_video": False,
                "comment_requested_video": True,
                "like_replied_comments": True,
                "favorite_commented_video": True,
                "follow_commented_up": False,
                "like_up_dynamics": False,
                "post_video_dynamic": False,
                "report_watching": False,
                "comment_monitor": True,
                "auto_reply": True,
                "reply_own_video_comments": True,
                "own_video_count": 10,
                "max_own_video_replies_per_check": 10,
                "greet_other_whales": True,
                "monitor_interval_minutes": 1,
                "reply_to_others": True,
                "reply_only_owner": False,
                "reply_interesting_comments": True,
                "mention_owner_on_interesting": False
            },
            "analysis": {
                "enable_frame_analysis": True,
                "transcription_mode": "off",
                "local_transcription_enabled": False,
                "local_transcription_model": "medium",
                "cloud_transcription": {
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "",
                    "model": "whisper-1"
                }
            },
            "diary": {
                "enabled": True
            },
            "memory": {
                "enabled": True,
                "use_self_review": True,
                "auto_self_review": True
            },
            "logging": {
                "level": "INFO",
                "file": "data/logs/bot.log",
                "max_file_size_mb": 10,
                "backup_count": 5
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
