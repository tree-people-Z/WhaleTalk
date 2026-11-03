# 鲸语 v2.4.0

这一版主要做“长期可维护”和“用起来更像成熟产品”，没有改动核心玩法。

## 安全

- B 站 Cookie 与配置文件里的 API Key 改用 Windows DPAPI 加密存储
  （`data/cookies.json`、`data/config.json` 里是 `dpapi:` 密文）。
  迁到其他 Windows 用户或机器时需要重新登录/填写密钥。
- 扫码登录不再关闭 TLS 校验，也不再依赖 bilibili-api 的私有属性。
- 新增单实例锁（`data/app.lock`），双开会被拒绝，避免两个 Agent 同时发评论。
- 更新包支持用发布页的 `SHA256SUMS.txt` 校验完整性。

## 稳定性

- AI 请求改为全异步客户端，带超时与指数退避重试；只重试连接错误、
  超时、429/5xx，鉴权错误不重试。
- SQLite 开启 WAL，每个线程独立 Session，修复 GUI 定时器与 Agent 线程
  共用连接可能导致的 `database is locked`。
- 数据库结构改用 `PRAGMA user_version` 版本化迁移。
- 依赖锁定到测试通过的小版本，避免上游大版本改接口。
- 修复 `report_watch` 缺少 `import random` 导致的静默失效。
- 修复 async 代码里调用阻塞 `requests` 的问题。

## Agent

- 实现文档中承诺的“单轮写操作上限”（默认 8 次，可在设置页调整）。
- 长对话自动压缩较早的工具结果，降低 token 成本。
- 上下文、总结审计、事件去重拆成独立模块，便于测试和扩展。

## 界面

- 新的桌面外壳：左侧分组导航 + 页头操作区，隐藏原生标签栏。
- 仪表盘改为 4 个 KPI 卡（带 7 天迷你趋势）、最近动作、账号与风控面板。
- 统一设计 token：卡片 14px 圆角、控件 9px、胶囊状态标签、统一配色。
- 设置页输入防抖，停止输入 400ms 后才落盘；一次保存只写一次配置。
- 控制台日志按级别着色。

## 工程

- 新增 `ARCHITECTURE.md`，把项目拆成入口、Agent、B 站接口、数据、UI、发布 6 个板块。
- 新增 CI（ruff + compileall + pytest，Python 3.10/3.12）。
- 清理约 1000 行未使用代码与遗留数据。
