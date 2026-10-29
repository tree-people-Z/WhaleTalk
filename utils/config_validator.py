"""配置验证模块 - 启动时快速失败"""

def validate_config(config) -> tuple[bool, str]:
    """
    验证配置文件的完整性和正确性
    
    Args:
        config: ConfigManager 实例
    
    Returns:
        (是否有效, 错误信息)
    """
    errors = []
    warnings = []
    
    # 1. AI 配置验证
    ai_provider = config.get('ai.provider')
    if not ai_provider:
        errors.append('❌ AI 提供商未配置（ai.provider）')
    else:
        # 验证 API Key
        api_key = config.get(f'ai.{ai_provider}_api_key', '')
        if not api_key:
            errors.append(f'❌ {ai_provider} API Key 未配置')
        elif len(api_key) < 10:
            errors.append(f'❌ {ai_provider} API Key 格式不正确（长度过短）')
        
        # 验证模型名称
        model = config.get(f'ai.{ai_provider}_model', '')
        if not model:
            warnings.append(f'⚠️ {ai_provider} 模型未指定，将使用默认值')
    
    # 2. B站配置验证
    owner_name = config.get('bilibili.owner_name', '')
    if owner_name:
        owner_name = owner_name.strip()
    if not owner_name:
        warnings.append('⚠️ 主人昵称未设置（bilibili.owner_name），@主人功能可能受影响')
    
    owner_uid = config.get('bilibili.owner_uid', 0)
    try:
        owner_uid = int(owner_uid)
        if owner_uid <= 0:
            warnings.append('⚠️ 主人 UID 未设置（bilibili.owner_uid）')
    except (TypeError, ValueError):
        warnings.append('⚠️ 主人 UID 格式不正确')
    
    # 3. 数值范围验证
    mention_score = config.get('limits.min_score_to_mention_owner', 13)
    try:
        mention_score = int(mention_score)
        if not 0 <= mention_score <= 20:
            errors.append(
                f'❌ @主人分数阈值应在 0-20 之间，当前为 {mention_score}'
            )
    except (TypeError, ValueError):
        errors.append('❌ @主人分数阈值格式不正确，应为整数')
    
    max_comments = config.get('limits.max_comments_per_day', 60)
    try:
        max_comments = int(max_comments)
        if max_comments < 1:
            errors.append('❌ 每日评论上限不能小于 1')
        elif max_comments > 200:
            warnings.append(
                f'⚠️ 每日评论上限较高（{max_comments}），建议设置在 1-200 之间'
            )
    except (TypeError, ValueError):
        errors.append('❌ 每日评论上限格式不正确，应为整数')
    
    # 4. 时间间隔验证
    interval_min = config.get('schedule.browse_interval_min_minutes', 30)
    interval_max = config.get('schedule.browse_interval_max_minutes', 60)
    try:
        interval_min = int(interval_min)
        interval_max = int(interval_max)
        
        if interval_min < 5:
            warnings.append(
                f'⚠️ 最小运行间隔过短（{interval_min}分钟），容易触发风控'
            )
        if interval_max < interval_min:
            errors.append(
                f'❌ 最大运行间隔（{interval_max}）不能小于最小间隔（{interval_min}）'
            )
    except (TypeError, ValueError):
        errors.append('❌ 运行间隔格式不正确，应为整数')
    
    # 构建返回消息
    if errors:
        msg_parts = ['配置验证失败，请修复以下问题：\n']
        msg_parts.extend(f'{e}\n' for e in errors)
        if warnings:
            msg_parts.append('\n注意事项：\n')
            msg_parts.extend(f'{w}\n' for w in warnings)
        return False, ''.join(msg_parts)
    
    if warnings:
        msg_parts = ['配置验证通过，但有以下注意事项：\n']
        msg_parts.extend(f'{w}\n' for w in warnings)
        return True, ''.join(msg_parts)
    
    return True, '✅ 配置验证通过'
