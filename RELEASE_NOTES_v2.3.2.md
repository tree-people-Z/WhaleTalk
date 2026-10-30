# 鲸语 v2.3.2

本版为便携 ZIP 发布，已内置 ffmpeg，解压后运行 `WhaleTalk\WhaleTalk.exe`。

## 本次修复

### 退出 / 后台线程崩溃
- 移除所有 `QThread.finished -> deleteLater` 的销毁方式
- 避免线程 `run` 栈未退出时销毁 QThread 导致 `Qt6Core.dll 0xc0000409`
- 长期记忆、更新检查/下载、评论加载、私信加载/发送线程都改为由 Qt 父对象回收
- 退出时等待长期记忆、本地模型准备、评论/私信线程
- 仍有后台线程运行时拒绝退出并提示，不再强行销毁窗口

### 诊断
- WER 崩溃转储已启用，下次异常会生成 `data/crash_dumps/WhaleTalk.exe.<PID>.dmp`

## 下载

仅提供 `WhaleTalk-Windows-x64.zip`，单文件版暂不提供。

## 校验

`SHA256SUMS.txt` 内含 ZIP 的 SHA256。
