# 崩溃转储（Crash Dump）

## 当前配置

已在 Windows WER 中为 `WhaleTalk.exe` 启用完整崩溃转储：

```text
注册表: HKLM\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\WhaleTalk.exe
DumpFolder: <安装目录>\data\crash_dumps
DumpType:   2（完整 dump）
DumpCount:  3（最多保留 3 个）
```

对应本机路径：

```text
C:\Users\tree-\Desktop\WhaleTalk-Windows-x64\WhaleTalk\data\crash_dumps
```

## 下次崩溃时

程序崩溃后，该目录会出现：

```text
WhaleTalk.exe.<PID>.dmp
```

把这个 `.dmp` 文件发给开发者即可定位 `Qt6Core.dll 0xc0000409`。

## 已验证

用同名测试程序触发 `FailFast`（同样是 `0xc0000409`），WER 成功生成了 68MB 的 dump，说明配置生效。

## 如果配置丢失

以管理员身份运行：

```text
tools\enable_wer_localdumps.ps1
```

脚本会重新写入 WER 配置，并把结果记录到：

```text
data\crash_dumps\enable_wer.log
```

## 说明

- 本机普通权限无法写 HKLM，所以启用时需要一次管理员权限（UAC）。
- 完整 dump 可能较大，崩溃后建议只保留最近 1-2 个。
- dump 包含进程内存，可能含登录凭证，发送前注意隐私。
