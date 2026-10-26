# 多平台适配调研：QQ、X（推特）、小红书

- 分支：`research/multi-platform`
- 基线：`master` / `0acb232`（v2.2.2）
- 性质：只做调研和架构建议，不改主分支行为
- 调研时间：2026-10

---

## 1. 结论先说

| 平台 | 自动化可行性 | 推荐优先级 | 主要原因 |
|---|---|---|---|
| QQ | 中高，但必须走官方机器人 | 1 | 有正式 OpenAPI、WebSocket/WebHook、群聊/单聊；需要主体认证和审核 |
| X（推特） | 中，成本敏感 | 2 | 有正式 API，可发帖/回复/私信；但按量计费，读写都花钱，规则限制多 |
| 小红书 | 低，不建议自动发布 | 3 | 官方开放平台主要面向企业/品牌，个人创作者没有发布 API；逆向/浏览器自动化有封号风险 |

建议顺序：

1. 先做平台抽象层，不改变 B 站现有行为
2. 接 QQ 官方机器人，先文本、先白名单群
3. 接 X 官方 API，先只读 + 少量回复，设预算上限
4. 小红书只做只读/人工辅助，不做自动发布和自动评论

---

## 2. 当前代码的耦合点

### 2.1 事件采集

`core/comment_events.py`：

- 扫描 B 站自己评论楼
- 扫描自己投稿视频顶层评论
- 读取 B 站 `@` 通知
- 处理 `rpid`、`root`、`parent`、`bvid`

`core/comment_manager.py`：

- 直接依赖 `BilibiliAPI`
- 直接构造 `ConversationAgent`
- 发送回复、私信、视频评论
- 冷却、每日上限、去重

### 2.2 对话 Agent

`core/conversation_agent.py`：

- 输入是 B 站风格事件：
  - `scope`
  - `rpid`
  - `bvid`
  - `aid`
  - `root_rpid`
  - `is_direct_at`
- 工具是 B 站专用：
  - `get_comment_thread`
  - `get_video_info`
  - `find_requested_video`
  - `comment_on_video`
  - `reply_comment`
  - `like_comment`
  - `reply_dm`

### 2.3 B 站接口层

`core/bilibili_api.py` 目前是：

```text
BilibiliAPI
├─ BiliDMMixin          私信 / @
├─ BiliCommentMixin     评论读取 / 发送 / 点赞
└─ BiliInteractMixin    收藏 / 关注 / 动态 / 弹幕 / 投币
```

职责已经拆开，但类名、鉴权、错误处理和事件格式仍然绑定 B 站。

### 2.4 数据库

`utils/database.py` 的表大量使用 B 站字段：

- `videos`: `bvid`, `aid`
- `comments`: `bvid`, `aid`, `rpid`, `thread_root`
- `memory_events`: `bvid`, `aid`, `rpid`
- `thread_states`: 以 B 站评论楼为 key
- `likes`, `media_assets`, `private_chat_state`

### 2.5 UI 和调度

- `gui/settings_page.py` 有 B 站登录、B 站参数
- `gui/main_window.py` 直接启动 B 站评论检查、自动运营
- `core/scheduler.py` 的巡视和回复检查是 B 站内容流水线

### 2.6 可复用的部分

这些模块基本与平台无关，可以直接复用：

- `core/conversation_agent.py` 的对话循环
- `core/agent_protocol.py`
- `core/ai_client.py`
- `core/long_term_memory.py`
- `core/daily_diary.py`
- `utils/persona_defaults.py`
- 日记、记忆、人格、冷却和概率策略

---

## 3. 平台调研

### 3.1 QQ

官方入口：

- [QQ Bot 介绍与接入指南](https://bot.q.qq.com/wiki/)
- [QQ Bot API 调用指南](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/api-call-guide.html)
- QQ 开放平台：<https://q.qq.com/>

官方能力：

- 运行在 QQ 频道、QQ 群、消息列表单聊
- 支持 WebSocket 和 WebHook 两种事件回调
- OpenAPI 使用 `Authorization: QQBot {ACCESS_TOKEN}`
- 有 `user_openid`、`group_openid`、`member_openid`
- 有消息、群管理、频道管理接口
- 错误码区分限频、权限、内容安全、主动消息限制

关键限制：

- 需要 QQ 开放平台注册、主体认证、创建机器人、配置服务范围
- 个人认证：暂不支持公开使用，进群数量上限 500
- 企业认证：服务范围可公开
- 机器人只能加入创建者是群主/管理员的群（未认证情况）
- 有主动消息限制、内容安全打击、消息审核
- 不同 AppID 的 openid 不互通

适配判断：

- **可以做，但要走官方机器人，不要用个人 QQ 挂协议**
- 第一版只做：
  - 群聊中被 @
  - 单聊
  - 文本回复
  - 白名单群
- 不做：
  - 主动私聊陌生人
  - 批量加群
  - 自动发图/文件
  - 绕过审核的协议端

社区方案：

- OneBot / NapCat 一类协议端可以快速接个人 QQ，但不符合腾讯用户协议，有风控和封号风险，不适合作为正式功能。
- 可以参考其事件模型，但不要直接依赖。

### 3.2 X（推特）

官方能力：

- X API v2
- OAuth 2.0
- 发帖、回复、删除、读取、私信等
- 有 app 级和 user 级速率限制
- 官方速率限制文档：
  <https://docs.x.com/x-api/fundamentals/rate-limits>
- 官方开发者入口：
  <https://developer.x.com/>

2026 年的变化：

- X API 已转向按量计费/付费额度模式，旧的 Free/Basic/Pro 方案在调整
- 发帖、回复、私信都可能产生费用
- 具体价格和额度会变，接入前必须以开发者后台为准

适配判断：

- **可以做，但必须做预算控制**
- 第一版只做：
  - 读取被 @ 的帖子
  - 读取回复链
  - 文本回复
  - 白名单账号/关键词
- 不做：
  - 大规模搜索
  - 自动关注/点赞/转发
  - 主动私信
  - 高频回复

风险：

- API 成本不可控
- 自动化规则和平台政策
- 回复上下文和引用关系与 B 站不同
- 账号被限制或 API 权限被回收

### 3.3 小红书

官方入口：

- 小红书开放平台：<https://open.xiaohongshu.com/>

现状：

- 官方开放平台主要面向企业、品牌、商家、MCN
- 笔记发布、评论、私信等权限审核严格
- **个人创作者没有公开的“自动发布笔记”API**
- 市面上的“小红书自动发布/MCP”大多是：
  - 浏览器自动化
  - 逆向私有接口
  - 抓包模拟

这些方案的风险：

- 违反平台规则
- 触发风控、降权、封号
- 接口随时变化
- 账号资产不可恢复

适配判断：

- **不建议做自动发布、自动评论、自动私信**
- 可以做：
  - 只读内容导入
  - 人工确认后复制文案
  - 浏览器辅助，但必须人工点击发布
  - 数据导出和分析
- 不做：
  - 无人值守发布
  - 自动评论/私信
  - 私有接口逆向

---

## 4. 建议的抽象设计

### 4.1 统一事件

新增一个平台无关的事件结构：

```python
@dataclass
class PlatformEvent:
    platform: str              # bilibili / qq / x / xiaohongshu
    account_id: str
    event_id: str
    kind: str                  # mention / reply / dm / comment
    thread_id: str
    parent_id: str
    author_id: str
    author_name: str
    content: str
    media: list[str]
    created_at: str
    is_direct: bool
    mentioned_users: list[str]
    raw: dict
```

B 站事件可以映射成这个结构，QQ/X 也映射成这个结构。

### 4.2 平台适配器

```python
class PlatformAdapter(Protocol):
    name: str

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def poll_events(self, cursor: str | None) -> list[PlatformEvent]: ...
    async def get_context(self, event: PlatformEvent) -> dict: ...
    async def get_content(self, content_id: str) -> dict: ...
    async def find_requested_content(self, text: str, author_id: str) -> dict | None: ...
    async def reply(self, event: PlatformEvent, text: str) -> bool: ...
    async def send_dm(self, user_id: str, text: str) -> bool: ...
    async def comment_on_content(self, content_id: str, text: str) -> bool: ...
```

能力声明：

```python
capabilities = {
    "reply": True,
    "dm": True,
    "comment": False,
    "like": False,
    "media": False,
    "search": False,
}
```

Agent 只调用适配器暴露的能力，不直接 import B 站模块。

### 4.3 Agent 工具平台化

当前 B 站工具改成平台无关名称：

| 现在 | 建议 |
|---|---|
| `get_comment_thread` | `get_thread_context` |
| `get_video_info` | `get_content_info` |
| `find_requested_video` | `find_requested_content` |
| `comment_on_video` | `comment_on_content` |
| `reply_comment` | `reply` |
| `like_comment` | `like` |

工具参数里不再出现 `bvid`、`aid`、`rpid`，改用：

```json
{
  "content_id": "...",
  "thread_id": "...",
  "parent_id": "..."
}
```

### 4.4 策略层

平台差异放在策略层，不放在 Agent 里：

```python
PlatformPolicy:
    max_replies_per_day
    max_replies_per_thread
    cooldown_seconds
    allow_proactive
    allow_dm
    allow_comment
    require_whitelist
    budget_per_day
```

B 站沿用现有 60 条/天、10 分钟冷却、6 条/楼。  
QQ 和 X 用各自更保守的上限。

### 4.5 数据层

两种方案：

#### 方案 A：加平台字段（推荐，改动小）

给现有表加：

```text
platform
external_id
```

保留 B 站字段作为兼容字段。  
新平台数据写入同一张表，用 `platform` 区分。

#### 方案 B：新建通用表

```text
platform_events
platform_threads
platform_contents
```

B 站旧表保留只读兼容。  
改动更干净，但迁移量大。

第一版建议方案 A，避免大规模迁移。

### 4.6 UI

设置页增加“平台”分组：

```text
平台
├─ B站（现有）
├─ QQ 机器人
├─ X
└─ 小红书（只读/辅助）
```

每个平台独立：

- 登录/凭证
- 启用开关
- 白名单
- 每日上限
- 预算上限

主界面增加平台筛选，不要把所有平台消息混在一个列表里。

---

## 5. 分阶段路线

### Phase 0：抽象层，不改行为

目标：

- 引入 `PlatformAdapter`
- 把 B 站事件映射成 `PlatformEvent`
- Agent 工具改成平台无关接口
- 保持 B 站现有行为不变
- 加回归测试

验收：

- B 站回复、@、私信、看视频请求全部不回归
- 现有 91 个测试通过

### Phase 1：QQ 官方机器人

范围：

- WebSocket 接事件
- 群聊被 @
- 单聊
- 文本回复
- 白名单群
- 独立每日上限

不做：

- 主动私聊
- 发图/文件
- 自动加群
- 协议端

验收：

- 测试群内被 @ 能正常回复
- 不在白名单的群不回复
- 限频/审核错误能被捕获
- 不影响 B 站

### Phase 2：X 官方 API

范围：

- OAuth 2.0
- 读取被 @
- 读取回复链
- 文本回复
- 每日预算上限
- 白名单/关键词

不做：

- 自动关注/点赞/转发
- 主动私信
- 大规模搜索

验收：

- 能读取并回复被 @
- 预算超限自动停止
- API 错误不影响其他平台

### Phase 3：小红书辅助

范围：

- 内容只读导入
- 文案生成
- 人工确认后复制/打开发布页
- 不自动提交

验收：

- 不会自动发布
- 不会自动评论/私信
- 不依赖私有接口

### Phase 4：统一运营面板

- 平台筛选
- 跨平台统计
- 独立策略
- 统一记忆（可选，默认按平台隔离）

---

## 6. 风险清单

### 账号风险

- QQ 个人协议端：违反用户协议，可能封号
- 小红书逆向/浏览器自动化：可能降权、封号
- X 自动化：可能触发平台反垃圾规则

### 成本风险

- X API 按量计费，读写都可能收费
- 多平台同时运行，AI token 和 API 费用叠加

### 数据风险

- 不同平台用户 ID 不能直接打通
- QQ openid 不同 AppID 不互通
- 私信/评论属于敏感数据，需要最小化存储

### 工程风险

- 平台事件模型差异大
- 媒体上传/下载格式不同
- 限频和错误码不同
- 平台接口随时可能变化

### 合规风险

- 需要遵守各平台开发者协议
- 不建议绕过审核、逆向私有接口
- 不建议批量骚扰、主动私信陌生人

---

## 7. 推荐决策

1. **不直接改主分支**
2. 先在 `research/multi-platform` 完成抽象层设计和 B 站回归
3. 第一个正式适配选 **QQ 官方机器人**
4. 第二个选 **X 官方 API**，必须带预算上限
5. 小红书只做 **人工辅助/只读**，不做自动发布
6. 每个平台独立开关、独立上限、独立白名单
7. 所有平台共用 Agent、人格、记忆，但策略和凭证隔离

---

## 8. 待确认问题

- QQ 机器人主体是个人还是企业？
- 是否接受 X API 按量计费？
- 小红书是只要“辅助发布”，还是坚持“全自动”？
- 多平台是否需要统一账号体系，还是各平台独立？
- 第一版是否只做文本，不做图片/视频？
- 是否需要跨平台统一收件箱？

---

## 9. 参考资料

- [QQ Bot 介绍与接入指南](https://bot.q.qq.com/wiki/)
- [QQ Bot API 调用指南](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/api-call-guide.html)
- [X API Rate Limits](https://docs.x.com/x-api/fundamentals/rate-limits)
- [X Developer Platform](https://developer.x.com/)
- [小红书开放平台](https://open.xiaohongshu.com/)
- [小红书开放平台 API 实战（第三方文章，仅作背景）](https://cloud.tencent.cn/developer/article/2735161)
- [OneBot/NapCat 风险说明（社区文章，仅作风险参考）](https://github.com/2710586329/dsh-qq)
