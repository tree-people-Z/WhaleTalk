"""
AI客户端模块
支持多种AI模型：OpenAI、Claude、各类国产大模型等
"""

import os
import base64
from pathlib import Path
from typing import Optional, List, Dict, Any
from enum import Enum
from loguru import logger

# 导入各AI SDK
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


class AIProvider(Enum):
    """AI提供商枚举"""
    OPENAI = "openai"
    CLAUDE = "claude"
    DEEPSEEK = "deepseek"
    QWEN = "qwen"


class AIClient:
    """AI客户端统一接口"""

    def __init__(
        self,
        provider: str = "openai",
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None
    ):
        """
        初始化AI客户端

        Args:
            provider: AI提供商 (openai/claude/deepseek/qwen)
            api_key: API密钥
            model: 模型名称
            base_url: 自定义API地址
        """
        self.provider = AIProvider(provider)
        configured_api_key = api_key or os.getenv(f"{provider.upper()}_API_KEY")
        self.api_key = configured_api_key.strip() if configured_api_key else None
        self.model = model or self._get_default_model()
        self.base_url = base_url

        # 初始化客户端
        self._init_client()

        logger.info(f"AI客户端初始化: {self.provider.value} / {self.model}")

    def _get_default_model(self) -> str:
        """获取默认模型名称"""
        defaults = {
            AIProvider.OPENAI: "gpt-4o-mini",
            AIProvider.CLAUDE: "claude-3-5-sonnet-20241022",
            AIProvider.DEEPSEEK: "deepseek-chat",
            AIProvider.QWEN: "qwen-plus"
        }
        return defaults.get(self.provider, "gpt-4o-mini")

    def _init_client(self):
        """初始化具体的AI客户端"""
        if self.provider == AIProvider.OPENAI or self.provider == AIProvider.DEEPSEEK:
            if not OPENAI_AVAILABLE:
                raise ImportError("请安装 openai 库: pip install openai")

            client_kwargs = {"api_key": self.api_key}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            elif self.provider == AIProvider.DEEPSEEK:
                client_kwargs["base_url"] = "https://api.deepseek.com"

            self.client = openai.OpenAI(**client_kwargs)

        elif self.provider == AIProvider.CLAUDE:
            if not ANTHROPIC_AVAILABLE:
                raise ImportError("请安装 anthropic 库: pip install anthropic")
            self.client = anthropic.Anthropic(api_key=self.api_key)

        elif self.provider == AIProvider.QWEN:
            if not OPENAI_AVAILABLE:
                raise ImportError("请安装 openai 库: pip install openai")
            self.client = openai.OpenAI(
                api_key=self.api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
            )

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> Optional[str]:
        """
        发送对话请求

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            temperature: 温度参数
            max_tokens: 最大token数

        Returns:
            AI回复内容
        """
        try:
            if self.provider == AIProvider.CLAUDE:
                # Claude使用不同的API格式
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=messages
                )
                return response.content[0].text

            else:
                # OpenAI兼容格式
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                return response.choices[0].message.content

        except Exception as e:
            logger.error(f"AI请求失败: {e}")
            return None

    def chat_sync(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> Optional[str]:
        """同步版本的chat（直接调用，不需要await）"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(
            self.chat(messages, temperature, max_tokens)
        )

    async def analyze_video(
        self,
        title: str,
        subtitle: Optional[str],
        comments: List[str],
        persona: str = "",
        video_metrics: Optional[Dict[str, Any]] = None,
        image_paths: Optional[List[str]] = None,
        text_evidence_type: str = '字幕',
    ) -> Dict[str, Any]:
        """
        分析视频是否值得关注

        Args:
            title: 视频标题
            subtitle: 字幕内容
            comments: 热门评论列表
            persona: 角色人设

        Returns:
            {
                "worthy": bool,
                "score": int (0-20),
                "reason": str,
                "summary": str
            }
        """
        # 构建分析提示词
        prompt = self._build_analyze_prompt(
            title, subtitle, comments, persona, video_metrics=video_metrics,
            text_evidence_type=text_evidence_type
        )
        if image_paths:
            prompt += f"\n本次附带了{min(len(image_paths), 5)}张从视频不同时间点抽取的画面，请把可见画面与文本证据一起判断。\n"

        messages = [
            {"role": "system", "content": "你是一个专业的内容分析助手。"},
            {"role": "user", "content": prompt}
        ]

        if image_paths:
            try:
                response = await self._chat_with_images(prompt, image_paths)
            except Exception as exc:
                logger.warning(f"视觉分析请求失败，改用文本信息分析: {exc}")
                response = await self.chat(messages, temperature=0.5)
        else:
            response = await self.chat(messages, temperature=0.5)

        if not response:
            return {
                "worthy": False,
                "score": 0,
                "reason": "AI分析失败",
                "summary": "",
                "error": True
            }

        # 解析响应
        try:
            # 期望格式：JSON或结构化文本
            import json
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`")
                if cleaned.lower().startswith("json"):
                    cleaned = cleaned[4:].strip()
            result = json.loads(cleaned)
            if not isinstance(result, dict):
                raise ValueError("AI分析结果不是JSON对象")
            return self._normalize_analysis_result(result)
        except (ValueError, TypeError):
            # 如果不是JSON，尝试从文本中提取
            return self._normalize_analysis_result(self._parse_analysis_response(response))

    @staticmethod
    def _encode_image(image_path: str) -> tuple[str, str]:
        """Resize/compress a sampled frame and return (mime type, base64 data)."""
        from PIL import Image

        with Image.open(image_path) as source:
            image = source.convert('RGB')
            image.thumbnail((960, 960))
            from io import BytesIO
            buffer = BytesIO()
            image.save(buffer, format='JPEG', quality=78, optimize=True)
        return 'image/jpeg', base64.b64encode(buffer.getvalue()).decode('ascii')

    async def _chat_with_images(self, prompt: str, image_paths: List[str]) -> str:
        """Send sampled images using the provider's native vision message format."""
        images = [self._encode_image(path) for path in image_paths[:5] if Path(path).is_file()]
        if not images:
            return await self.chat([{'role': 'user', 'content': prompt}], temperature=0.5) or ''
        if self.provider == AIProvider.CLAUDE:
            content = [{'type': 'text', 'text': prompt}]
            for mime_type, encoded in images:
                content.append({
                    'type': 'image',
                    'source': {'type': 'base64', 'media_type': mime_type, 'data': encoded},
                })
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                temperature=0.5,
                system='你是一个专业的视频内容分析助手。',
                messages=[{'role': 'user', 'content': content}],
            )
            return ''.join(block.text for block in response.content if getattr(block, 'type', '') == 'text')

        content = [{'type': 'text', 'text': prompt}]
        for mime_type, encoded in images:
            content.append({
                'type': 'image_url',
                'image_url': {'url': f'data:{mime_type};base64,{encoded}'},
            })
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {'role': 'system', 'content': '你是一个专业的视频内容分析助手。'},
                {'role': 'user', 'content': content},
            ],
            temperature=0.5,
            max_tokens=2000,
        )
        return response.choices[0].message.content or ''

    async def describe_image(self, image_path: str) -> Optional[str]:
        """Return a concise description for a single image via the configured model."""
        try:
            return await self._chat_with_images(
                '用中文简要描述这张视频画面中可见的内容，只描述图像证据，不推测前后剧情。',
                [image_path],
            )
        except Exception as exc:
            logger.warning(f"单帧视觉分析失败: {exc}")
            return None

    @staticmethod
    def _normalize_analysis_result(result: Dict[str, Any]) -> Dict[str, Any]:
        """规范AI分析字段，并将主人提醒限定在高兴趣评分。"""
        try:
            score = max(0, min(20, int(result.get("score", 0))))
        except (TypeError, ValueError):
            score = 0
        worthy = bool(result.get("worthy", score >= 13)) and score >= 13
        interesting = bool(result.get("interesting", score >= 17)) and score >= 17
        return {
            "worthy": worthy,
            "interesting": interesting,
            "notify_owner": interesting,
            "score": score,
            "reason": str(result.get("reason", ""))[:200],
            "summary": str(result.get("summary", ""))[:300],
            "confidence": result.get("confidence") if result.get("confidence") in {"low", "medium", "high"} else "medium",
            "tags": [str(tag)[:30] for tag in result.get("tags", [])[:8]]
            if isinstance(result.get("tags", []), list) else [],
        }

    def _build_analyze_prompt(
        self,
        title: str,
        subtitle: Optional[str],
        comments: List[str],
        persona: str,
        video_metrics: Optional[Dict[str, Any]] = None,
        text_evidence_type: str = '字幕',
    ) -> str:
        """构建视频分析提示词"""

        prompt_parts = []

        if persona:
            prompt_parts.append(f"# 你的身份\n{persona}\n")
            prompt_parts.append(
                "评分时把角色口吻与作品质量分开：不能因为题材不符合人设偏好就给好作品低分。\n"
            )

        prompt_parts.append(f"""# 任务
请分析以下视频是否值得你关注和分享。

# 视频信息
标题：{title}
""")

        if video_metrics:
            metric_lines = []
            for key, label in (("play", "播放量"), ("comment_count", "评论量"), ("like", "点赞数"),
                               ("favorites", "收藏数"), ("duration", "时长"),
                               ("author", "UP主")):
                value = video_metrics.get(key)
                if value not in (None, "", 0):
                    metric_lines.append(f"{label}：{value}")
            if metric_lines:
                prompt_parts.append("\n# 视频数据（热度权重参考）\n" + "\n".join(metric_lines) + "\n")

        if subtitle:
            prompt_parts.append(f"\n{text_evidence_type}内容（前2000字）：\n{subtitle[:2000]}\n")
        else:
            prompt_parts.append("\n[该视频没有字幕]\n")

        if comments:
            comments_text = "\n".join([f"- {c}" for c in comments[:10]])
            prompt_parts.append(f"\n热门评论：\n{comments_text}\n")

        prompt_parts.append("""
# 评分标准（评价作品质量，不评价它是否符合你个人口味）
请按以下四项综合打分，总分 20 分：
- 内容价值与准确性：0-8 分。知识、信息、观点或娱乐体验是否扎实、有用、有意思。
- 表达与完成度：0-4 分。结构、讲解、制作和节奏是否清楚、完整。
- 创意与感染力：0-3 分。是否有新意，能否让观众投入或产生共鸣。
- 观众反馈：0-5 分。播放量和评论量是明确的正向热度信号，评论量体现主动参与，需结合题材、发布时间和评论质量判断；高播放或高评论可显著提高这一项，但不能单独证明内容质量。

热度参考：比较视频数据时优先看播放量与评论量。播放量达到百万级或评论量达到数千级，通常应在观众反馈项给出较高分；两项都突出且评论反馈积极时可给满分。数据缺失或视频发布时间很短时不要臆测；热度只影响观众反馈项，不要把它等同于内容价值、表达质量或创意。

分数锚点：
- 0-5：明显低质、信息错误或几乎没有有效内容；不能仅因题材小众或不合角色口味打这个分。
- 6-9：完成度或内容价值偏弱。
- 10-12：普通、合格，有一定内容但亮点有限。
- 13-15：确实不错，内容清楚、有价值或有趣，值得关注。
- 16-18：质量突出，多个方面表现优秀。
- 19-20：少见的杰出作品，证据充分才给。

字幕、标题、简介或评论不足时，应降低判断把握并在 reason 中说明依据不足；不要把“看不到字幕”当成作品质量差，也不要凭空猜测内容。若附带视频帧，只根据抽取的少量画面描述可见证据，不要推测未展示的动作、前后剧情或完整视频内容。热门评论可作为观众反馈，但不能替代内容证据。

# 输出格式（JSON）
```json
{
  "worthy": true/false,
  "interesting": true/false,
  "score": 0-20,
  "reason": "为什么值得/不值得（50字内）",
  "summary": "用一句话总结这个视频（30字内）",
  "tags": ["内容主题"],
  "confidence": "low/medium/high"
}
```

score 表示客观作品质量。confidence表示证据对判断的支持程度：字幕/转写和多帧画面相互印证时通常为high；只有标题、评论或少量画面时通常为low或medium。只有评分达到17分且内容确实有突出的分享价值时，interesting才为true；不要求题材必须符合角色偏好。

请直接输出JSON，不要其他内容。
""")

        return "".join(prompt_parts)

    def _parse_analysis_response(self, response: str) -> Dict[str, Any]:
        """从文本响应中解析分析结果"""
        # 简单的文本解析
        score = 0
        worthy = False
        reason = ""
        summary = ""

        lines = response.lower()

        # 尝试提取分数
        if "score" in lines or "分数" in lines or "评分" in lines:
            import re
            score_match = re.search(r'(\d+)', lines)
            if score_match:
                score = int(score_match.group(1))
                score = min(max(score, 0), 20)

        worthy = score >= 13  # 默认阈值

        # 提取原因和总结（简化版本）
        reason = "基于内容分析"
        summary = response[:50]

        return {
            "worthy": worthy,
            "score": score,
            "reason": reason,
            "summary": summary
        }

    async def generate_comment(
        self,
        video_title: str,
        video_content: str,
        persona: str = "",
        mention_user: Optional[str] = None
    ) -> Optional[str]:
        """
        生成视频评论

        Args:
            video_title: 视频标题
            video_content: 视频内容摘要
            persona: 角色人设
            mention_user: 要@的用户名

        Returns:
            生成的评论文本
        """
        prompt_parts = []

        if persona:
            prompt_parts.append(f"# 你的身份\n{persona}\n")

        prompt_parts.append(f"""# 任务
为以下视频写一条评论。

# 视频信息
标题：{video_title}
内容：{video_content}

# 要求
1. 评论要贴合视频内容，展现你真的看过
2. 语气自然，符合你的人设
3. 20-50字，不要太长
4. 不要过度吹捧，保持真诚
5. 可以适当使用emoji，但不要过多
""")

        if mention_user:
            prompt_parts.append(
                f"6. 请在评论中自然地提及 @{mention_user}（放在结尾或合适的句子里），不要省略。\n"
            )
        else:
            prompt_parts.append("6. 不要@主人或其他用户，也不要添加任何用户标签；像普通观众一样围绕视频内容自然聊天。\n")

        prompt_parts.append("\n直接输出评论内容，不要其他解释。")

        messages = [
            {"role": "system", "content": "你是一个真实的B站用户，在认真观看后发表评论。"},
            {"role": "user", "content": "".join(prompt_parts)}
        ]

        response = await self.chat(messages, temperature=0.8, max_tokens=200)

        if response:
            # 清理可能的引号等
            response = response.strip().strip('"\'')
            if mention_user:
                # 阈值通过时确保模型不会随机省略 @主人。
                if '@' not in response:
                    response = f"{response.rstrip()} @{mention_user}"
            else:
                # Enforce the opt-out even if the model ignores its prompt.
                import re
                response = re.sub(r'@[一-鿿A-Za-z0-9_\-]+', '', response)
                response = re.sub(r'\s{2,}', ' ', response).strip()
            logger.info(f"生成评论: {response}")

        return response

    async def generate_reply(
        self,
        original_comment: str,
        video_context: str,
        persona: str = ""
    ) -> Optional[str]:
        """
        生成对评论的回复

        Args:
            original_comment: 原始评论内容
            video_context: 视频相关上下文
            persona: 角色人设

        Returns:
            回复内容
        """
        prompt_parts = []

        if persona:
            prompt_parts.append(f"# 你的身份\n{persona}\n")

        prompt_parts.append(f"""# 任务
回复以下评论。

# 视频背景
{video_context}

# 对方的评论
{original_comment}

# 要求
1. 回复要友好、自然
2. 如果是提问，认真回答
3. 如果是夸奖，礼貌感谢
4. 如果是批评，理性回应
5. 10-30字，简洁明了
6. 不与人争吵，保持礼貌

直接输出回复内容。
""")

        messages = [
            {"role": "system", "content": "你在B站评论区与人友好互动。"},
            {"role": "user", "content": "".join(prompt_parts)}
        ]

        response = await self.chat(messages, temperature=0.7, max_tokens=150)

        if response:
            response = response.strip().strip('"\'')
            logger.info(f"生成回复: {response}")

        return response


# 使用示例
if __name__ == "__main__":
    import asyncio

    async def test():
        # 测试OpenAI
        client = AIClient(provider="openai", api_key="your-key")

        result = await client.analyze_video(
            title="Python教程：10分钟学会装饰器",
            subtitle="大家好，今天我们来讲Python装饰器...",
            comments=["讲得太好了！", "终于看懂了"],
            persona="我是一个热爱编程的AI助手"
        )

        print(result)

    asyncio.run(test())
