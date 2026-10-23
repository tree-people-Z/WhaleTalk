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
                self._normalize_secrets()
                logger.info(f"配置已加载: {self.config_path}")
            except Exception as e:
                logger.error(f"加载配置失败: {e}")
                self.config = self.get_default_config()
        else:
            logger.info("配置文件不存在，使用默认配置")
            self.config = self.get_default_config()

    def save(self):
        """保存配置"""
        try:
            self._normalize_secrets()
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            logger.info("配置已保存")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

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
                "name": "DeepSeek娘",
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
                "max_comments_per_day": 999,
                "max_videos_per_run": 20,
                "same_video_cooldown_days": 7,
                "min_score_to_comment": 10,
                "min_score_to_mention_owner": 17,
                "mention_owner_on_interesting": False
            },
            "interaction": {
                "auto_comment": True,
                "comment_monitor": True,
                "auto_reply": True,
                "monitor_interval_minutes": 1,
                "reply_to_others": True,
                "reply_only_owner": False,
                "reply_interesting_comments": True,
                "mention_owner_on_interesting": False
            },
            "analysis": {
                "enable_frame_analysis": True,
                "local_transcription_enabled": False,
                "local_transcription_model": "small"
            },
            "diary": {
                "enabled": True
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
