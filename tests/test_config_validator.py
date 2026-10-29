"""配置验证器测试"""
import unittest
from unittest.mock import Mock
from utils.config_validator import validate_config


class ConfigValidatorTests(unittest.TestCase):
    def test_valid_config_passes(self):
        """测试正确的配置通过验证"""
        config = Mock()
        config.get.side_effect = lambda key, default=None: {
            'ai.provider': 'openai',
            'ai.api_key': 'sk-test1234567890',
            'ai.model': 'gpt-4',
            'bilibili.owner_name': 'TestUser',
            'bilibili.owner_uid': 123456,
            'limits.min_score_to_mention_owner': 13,
            'limits.max_comments_per_day': 60,
            'schedule.browse_interval_min_minutes': 30,
            'schedule.browse_interval_max_minutes': 60,
        }.get(key, default)
        
        valid, msg = validate_config(config)
        self.assertTrue(valid)
        self.assertIn('✅', msg)
    
    def test_missing_ai_provider_fails(self):
        """测试缺少 AI 提供商配置"""
        config = Mock()
        config.get.return_value = None
        
        valid, msg = validate_config(config)
        self.assertFalse(valid)
        self.assertIn('AI 提供商未配置', msg)
    
    def test_invalid_api_key_fails(self):
        """测试无效的 API Key"""
        config = Mock()
        config.get.side_effect = lambda key, default=None: {
            'ai.provider': 'openai',
            'ai.api_key': 'x',  # 太短
        }.get(key, default)
        
        valid, msg = validate_config(config)
        self.assertFalse(valid)
        self.assertIn('API Key 格式不正确', msg)
    
    def test_invalid_mention_probability_fails(self):
        """测试超出范围的@主人分数阈值"""
        config = Mock()
        config.get.side_effect = lambda key, default=None: {
            'ai.provider': 'openai',
            'ai.api_key': 'sk-test1234567890',
            'limits.min_score_to_mention_owner': 25,  # 超出范围
        }.get(key, default)
        
        valid, msg = validate_config(config)
        self.assertFalse(valid)
        self.assertIn('@主人分数阈值应在 0-20 之间', msg)
    
    def test_invalid_interval_range_fails(self):
        """测试最大间隔小于最小间隔"""
        config = Mock()
        config.get.side_effect = lambda key, default=None: {
            'ai.provider': 'openai',
            'ai.openai_api_key': 'sk-test1234567890',
            'schedule.browse_interval_min_minutes': 60,
            'schedule.browse_interval_max_minutes': 30,  # 小于最小
        }.get(key, default)
        
        valid, msg = validate_config(config)
        self.assertFalse(valid)
        self.assertIn('最大运行间隔', msg)
        self.assertIn('不能小于最小间隔', msg)
    
    def test_warnings_dont_fail_validation(self):
        """测试警告不会导致验证失败"""
        config = Mock()
        config.get.side_effect = lambda key, default=None: {
            'ai.provider': 'openai',
            'ai.openai_api_key': 'sk-test1234567890',
            'bilibili.owner_name': '',  # 空的，但只是警告
            'limits.max_comments_per_day': 250,  # 过高，但只是警告
        }.get(key, default)
        
        valid, msg = validate_config(config)
        self.assertTrue(valid)
        self.assertIn('⚠️', msg)


if __name__ == '__main__':
    unittest.main()
