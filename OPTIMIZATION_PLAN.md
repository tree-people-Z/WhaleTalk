# 🐋 鲸语 AI 运营助手 - 务实优化方案

## 原则：安全第一，小步快跑

```
✅ 每次改动 < 3 个文件
✅ 每次改动可独立回滚
✅ 现有 112 个测试必须全部通过
✅ 不引入破坏性依赖
```

---

## 📋 Phase 1: 紧急修复（3天）⭐⭐⭐⭐⭐

### 任务 1.1：异常处理清理（1天）

**目标**：修复最危险的异常捕获

**步骤**：

1. **识别危险位置**
```powershell
cd C:\Users\tree-\Desktop\bili
Select-String -Path core\*.py -Pattern 'except.*noqa.*BLE001' -Context 2,5 | Out-File dangerous_exceptions.txt
```

2. **修复模板**（每个位置5分钟）
```python
# 优先修复这些位置：
# - core/free_agent.py 中的 asyncio 异常
# - gui/main_window.py 中的 QThread 异常
# - core/bilibili_api.py 中的网络异常

# 旧代码
try:
    result = await some_operation()
except Exception as exc:  # noqa: BLE001
    logger.warning(f'操作失败: {exc}')
    return None

# 新代码
try:
    result = await some_operation()
except asyncio.CancelledError:
    raise  # 不要吞掉取消信号
except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
    logger.warning(f'网络错误: {exc}')
    return None
except Exception as exc:
    logger.exception(f'未预期错误: {exc}')
    return None
```

3. **验收**
```powershell
# 运行测试
python -m pytest tests -v

# 手动测试
# - 启动程序
# - 运行一轮完整流程
# - 检查日志无异常
```

**回滚方案**：
```powershell
git checkout HEAD -- core/free_agent.py
```

---

### 任务 1.2：配置验证（1天）

**目标**：启动时检查配置，快速失败

**步骤**：

1. **创建验证模块** `utils/config_validator.py`（已创建，需补充）
```python
def validate_config(config):
    """启动时验证配置"""
    errors = []
    
    # AI配置
    ai_provider = config.get('ai.provider')
    if not ai_provider:
        errors.append('❌ AI提供商未配置')
    else:
        api_key = config.get(f'ai.{ai_provider}_api_key')
        if not api_key or len(api_key) < 10:
            errors.append(f'❌ {ai_provider} API Key 无效')
    
    # B站配置
    owner_name = config.get('bilibili.owner_name', '')
    if not owner_name:
        errors.append('❌ 主人昵称未设置（影响@功能）')
    
    # 数值范围
    mention_prob = config.get('interaction.owner_mention_probability', 35)
    if not 0 <= mention_prob <= 100:
        errors.append(f'❌ @主人概率应在0-100之间，当前为{mention_prob}')
    
    max_comments = config.get('limits.max_comments_per_day', 60)
    if max_comments < 1 or max_comments > 200:
        errors.append(f'⚠️ 每日评论上限建议设置在1-200之间，当前为{max_comments}')
    
    if errors:
        return False, '\n'.join(errors)
    return True, ''
```

2. **集成到主程序** `main.py`
```python
# 在创建主窗口前添加
from utils.config_validator import validate_config

valid, error_msg = validate_config(config)
if not valid:
    QMessageBox.critical(
        None,
        '⚙️ 配置检查失败',
        f'请先完成以下配置：\n\n{error_msg}\n\n'
        f'点击确定后将打开设置页面'
    )
    # 直接打开设置页让用户配置
    settings_page = SettingsPage(config)
    settings_page.show()
```

3. **验收**
- [ ] 删除 `data/config.json` 中的 `ai.provider`，重启应提示
- [ ] 设置 `owner_mention_probability` 为 150，重启应提示
- [ ] 配置正确时不应有弹窗

**回滚方案**：
```powershell
git checkout HEAD -- utils/config_validator.py main.py
```

---

### 任务 1.3：QThread 防御（1天）

**目标**：防止窗口关闭时崩溃

**步骤**：

1. **检查当前 QThread 使用**
```powershell
Select-String -Path gui\*.py -Pattern 'QThread|moveToThread' -Context 3,3
```

2. **统一关闭逻辑** `gui/main_window.py`
```python
def closeEvent(self, event):
    """窗口关闭事件"""
    logger.info('正在关闭窗口...')
    
    # 1. 停止定时器
    if hasattr(self, '_reply_poll_timer'):
        self._reply_poll_timer.stop()
    if hasattr(self, '_update_recheck_timer'):
        self._update_recheck_timer.stop()
    
    # 2. 停止所有 worker（如果存在）
    workers = [
        getattr(self, attr) 
        for attr in dir(self) 
        if attr.endswith('_worker') and isinstance(getattr(self, attr), QThread)
    ]
    
    for worker in workers:
        if worker.isRunning():
            logger.info(f'正在停止 {worker.__class__.__name__}...')
            worker.requestInterruption()  # 发送中断信号
            worker.wait(3000)  # 等待最多3秒
            
            if worker.isRunning():
                logger.warning(f'{worker.__class__.__name__} 未响应，强制终止')
                worker.terminate()
                worker.wait(1000)
    
    # 3. 保存窗口状态
    self.save_window_state()
    
    event.accept()
```

3. **验收**
- [ ] 正常关闭窗口不崩溃
- [ ] 运行任务时关闭窗口不崩溃
- [ ] 日志中无 QThread 相关警告

**回滚方案**：
```powershell
git checkout HEAD -- gui/main_window.py
```

---

## 📋 Phase 2: 性能优化（5天）⭐⭐⭐⭐

### 任务 2.1：简单缓存（2天）

**目标**：减少重复 API 调用

**已完成**：
- ✅ 创建了 `utils/simple_cache.py`

**步骤**：

1. **安装依赖**（如果没有）
```powershell
pip install cachetools
```

2. **应用到视频信息获取** `core/bilibili_api.py`
```python
# 在文件顶部导入
from utils.simple_cache import cached_video, cached_comments

# 找到 get_video_info 方法（约617行），添加装饰器
@cached_video
async def get_video_info(self, bvid: str) -> Optional[Dict[str, Any]]:
    """获取视频详细信息"""
    # 原有代码不变
    ...

# 找到 get_comments 方法，添加装饰器
@cached_comments
async def get_comments(self, aid: int, ...) -> List[Dict]:
    """获取评论列表"""
    # 原有代码不变
    ...
```

3. **测试缓存效果**
```python
# tests/test_cache.py（新建）
import pytest
from core.bilibili_api import BilibiliAPI
from utils.simple_cache import clear_cache

@pytest.mark.asyncio
async def test_video_cache():
    """测试视频信息缓存"""
    api = BilibiliAPI()
    clear_cache()
    
    # 第一次调用
    result1 = await api.get_video_info('BV1test')
    
    # 第二次调用应该命中缓存
    result2 = await api.get_video_info('BV1test')
    
    assert result1 == result2
```

4. **验收**
```powershell
# 运行测试
python -m pytest tests/test_cache.py -v

# 手动验证：查看日志
# - 同一个视频第二次访问应该更快
# - 日志中应该少了重复的 API 请求
```

**预期收益**：
- API 请求量减少 40-60%
- 视频信息获取速度提升 5-10倍

**回滚方案**：
```powershell
git checkout HEAD -- core/bilibili_api.py
rm utils/simple_cache.py
```

---

### 任务 2.2：日志异步化（2天）

**目标**：日志不阻塞主线程

**步骤**：

1. **创建异步日志管理器** `utils/async_logger.py`
```python
import queue
import threading
from pathlib import Path
from loguru import logger

class AsyncLogHandler:
    """异步日志处理器"""
    
    def __init__(self, log_dir='logs'):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        self.queue = queue.Queue(maxsize=10000)
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()
    
    def _worker(self):
        """后台写入日志"""
        log_file = self.log_dir / 'app.log'
        
        with open(log_file, 'a', encoding='utf-8', buffering=8192) as f:
            while True:
                try:
                    msg = self.queue.get(timeout=1)
                    if msg is None:  # 停止信号
                        break
                    f.write(msg + '\n')
                    f.flush()
                except queue.Empty:
                    continue
    
    def log(self, message):
        """添加日志到队列"""
        try:
            self.queue.put_nowait(message)
        except queue.Full:
            # 队列满时丢弃（避免阻塞）
            pass
    
    def stop(self):
        """停止日志写入"""
        self.queue.put(None)
        self.worker.join(timeout=3)

# 全局实例
_async_handler = None

def setup_async_logging():
    """配置异步日志"""
    global _async_handler
    _async_handler = AsyncLogHandler()
    
    # 配置 loguru
    logger.remove()  # 移除默认
    
    # GUI 控制台（INFO及以上）
    logger.add(
        lambda msg: gui_console_append(msg),
        level='INFO',
        format='{time:HH:mm:ss} | {level: <8} | {message}',
        filter=lambda r: r['extra'].get('show_in_gui', True)
    )
    
    # 异步文件（WARNING及以上）
    logger.add(
        lambda msg: _async_handler.log(msg),
        level='WARNING',
        format='{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{line} | {message}'
    )

def gui_console_append(message):
    """添加到GUI控制台（需要实现）"""
    pass
```

2. **集成到主程序** `main.py`
```python
from utils.async_logger import setup_async_logging

# 在程序启动早期调用
setup_async_logging()
```

3. **验收**
- [ ] 日志文件正常写入
- [ ] GUI 不会因为日志而卡顿
- [ ] 关闭程序时日志全部落盘

**预期收益**：
- GUI 响应速度提升 30%
- 磁盘 I/O 减少 80%

**回滚方案**：
```powershell
rm utils/async_logger.py
git checkout HEAD -- main.py
```

---

### 任务 2.3：批量 API 调用（1天）

**目标**：并发获取多个视频信息

**步骤**：

1. **添加批量方法** `core/bilibili_api.py`
```python
async def get_videos_info_batch(self, bvids: List[str]) -> Dict[str, Dict]:
    """批量获取视频信息
    
    Args:
        bvids: 视频 BV 号列表
    
    Returns:
        {bvid: info_dict} 映射
    """
    async def fetch_one(bvid):
        try:
            return bvid, await self.get_video_info(bvid)
        except Exception as e:
            logger.warning(f'获取视频 {bvid} 失败: {e}')
            return bvid, None
    
    # 并发获取，最多5个并发
    results = {}
    for i in range(0, len(bvids), 5):
        batch = bvids[i:i+5]
        batch_results = await asyncio.gather(
            *[fetch_one(bvid) for bvid in batch],
            return_exceptions=True
        )
        for bvid, info in batch_results:
            if isinstance(bvid, str):  # 不是异常
                results[bvid] = info
    
    return results
```

2. **使用批量方法** `core/free_agent.py`
```python
# 找到搜索视频后获取信息的地方
# 旧代码（串行）
for video in search_results:
    info = await self.bili_tool.call('get_video_info', {'bvid': video['bvid']})
    # ...

# 新代码（并行）
bvids = [v['bvid'] for v in search_results[:10]]
infos = await self.bili.get_videos_info_batch(bvids)
for bvid, info in infos.items():
    if info:
        # ...
```

3. **验收**
- [ ] 搜索后查看视频明显变快
- [ ] 测试通过

**预期收益**：
- 批量获取视频信息速度提升 5-8倍

**回滚方案**：
```powershell
git checkout HEAD -- core/bilibili_api.py core/free_agent.py
```

---

## 📋 Phase 3: 用户体验（3天）⭐⭐⭐⭐

### 任务 3.1：首次启动向导（2天）

**目标**：新用户5分钟完成配置

**步骤**：

1. **创建向导对话框** `gui/setup_wizard.py`（新文件）
```python
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QStackedWidget, QProgressBar, QLabel, QLineEdit,
    QComboBox, QMessageBox
)

class SetupWizard(QDialog):
    """首次启动向导"""
    
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setWindowTitle('🐋 欢迎使用鲸语 AI 运营助手')
        self.setMinimumSize(600, 500)
        
        # 页面
        self.pages = [
            WelcomePage(),
            AIConfigPage(config),
            BilibiliLoginPage(config),
            PersonaPage(config)
        ]
        
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # 进度条
        self.progress = QProgressBar()
        self.progress.setMaximum(len(self.pages))
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        
        # 页面容器
        self.stack = QStackedWidget()
        for page in self.pages:
            self.stack.addWidget(page)
        layout.addWidget(self.stack)
        
        # 按钮
        btn_layout = QHBoxLayout()
        self.prev_btn = QPushButton('⬅️ 上一步')
        self.next_btn = QPushButton('下一步 ➡️')
        self.finish_btn = QPushButton('✅ 完成设置')
        
        self.prev_btn.clicked.connect(self.prev_page)
        self.next_btn.clicked.connect(self.next_page)
        self.finish_btn.clicked.connect(self.accept)
        
        btn_layout.addWidget(self.prev_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.next_btn)
        btn_layout.addWidget(self.finish_btn)
        layout.addLayout(btn_layout)
        
        self.update_buttons()
    
    def next_page(self):
        current_page = self.pages[self.stack.currentIndex()]
        if not current_page.validate():
            QMessageBox.warning(self, '提示', '请完成当前步骤的配置')
            return
        
        # 保存当前页设置
        current_page.save()
        
        # 下一页
        self.stack.setCurrentIndex(self.stack.currentIndex() + 1)
        self.progress.setValue(self.stack.currentIndex() + 1)
        self.update_buttons()
    
    def prev_page(self):
        self.stack.setCurrentIndex(self.stack.currentIndex() - 1)
        self.progress.setValue(self.stack.currentIndex() + 1)
        self.update_buttons()
    
    def update_buttons(self):
        idx = self.stack.currentIndex()
        self.prev_btn.setEnabled(idx > 0)
        self.next_btn.setVisible(idx < len(self.pages) - 1)
        self.finish_btn.setVisible(idx == len(self.pages) - 1)

# 各个页面的实现...
```

2. **集成到主程序** `main.py`
```python
from gui.setup_wizard import SetupWizard

# 检查是否首次启动
if not config.get('setup.completed', False):
    wizard = SetupWizard(config)
    if wizard.exec() == QDialog.DialogCode.Accepted:
        config.set('setup.completed', True)
        config.save()
    else:
        # 用户取消，退出程序
        sys.exit(0)
```

3. **验收**
- [ ] 首次启动显示向导
- [ ] 完成向导后不再显示
- [ ] 可以通过删除 `setup.completed` 重新触发

**回滚方案**：
```powershell
rm gui/setup_wizard.py
git checkout HEAD -- main.py
```

---

### 任务 3.2：健康检查（1天）

**目标**：自动检测常见问题

**步骤**：

1. **创建健康检查模块** `utils/health_check.py`
```python
from datetime import datetime
from typing import List, Tuple

async def check_bilibili_login(api) -> Tuple[bool, str]:
    """检查B站登录状态"""
    try:
        info = await api.get_my_info()
        if info and info.get('mid'):
            return True, '✅ B站账号已登录'
        return False, '❌ B站登录已失效，请重新登录'
    except Exception as e:
        return False, f'❌ B站登录检查失败: {e}'

async def check_ai_api(config) -> Tuple[bool, str]:
    """检查AI API配置"""
    provider = config.get('ai.provider')
    api_key = config.get(f'ai.{provider}_api_key')
    
    if not api_key:
        return False, f'❌ {provider} API Key 未配置'
    
    # 简单验证（不实际调用，避免消耗额度）
    if len(api_key) < 10:
        return False, f'❌ {provider} API Key 格式不正确'
    
    return True, f'✅ {provider} API 配置正常'

async def check_disk_space() -> Tuple[bool, str]:
    """检查磁盘空间"""
    import shutil
    total, used, free = shutil.disk_usage('.')
    
    if free < 100 * 1024 * 1024:  # 小于100MB
        return False, f'⚠️ 磁盘空间不足: {free // 1024 // 1024}MB'
    
    return True, f'✅ 磁盘空间充足: {free // 1024 // 1024}MB'

async def run_health_checks(api, config) -> List[Tuple[bool, str]]:
    """运行所有健康检查"""
    checks = [
        check_bilibili_login(api),
        check_ai_api(config),
        check_disk_space()
    ]
    
    results = []
    for check in checks:
        try:
            result = await check
            results.append(result)
        except Exception as e:
            results.append((False, f'检查失败: {e}'))
    
    return results
```

2. **定期执行** `gui/main_window.py`
```python
# 添加定时器
self._health_check_timer = QTimer(self)
self._health_check_timer.timeout.connect(self.run_health_check)
self._health_check_timer.start(60000)  # 每分钟检查一次

async def run_health_check(self):
    """运行健康检查"""
    from utils.health_check import run_health_checks
    
    results = await run_health_checks(self.bili_api, self.config)
    
    # 统计问题
    issues = [msg for ok, msg in results if not ok]
    
    if issues:
        # 状态栏显示
        self.statusBar().showMessage(
            f'⚠️ 发现 {len(issues)} 个问题',
            10000
        )
        
        # 托盘通知（不要频繁打扰）
        if not hasattr(self, '_last_health_warning'):
            self._last_health_warning = None
        
        now = datetime.now()
        if (not self._last_health_warning or 
            (now - self._last_health_warning).seconds > 3600):  # 1小时通知一次
            self.tray_icon.showMessage(
                '健康检查',
                '\n'.join(issues),
                QSystemTrayIcon.MessageIcon.Warning,
                5000
            )
            self._last_health_warning = now
```

3. **验收**
- [ ] 登录失效时提示
- [ ] 磁盘空间不足时提示
- [ ] 不会频繁打扰用户

**回滚方案**：
```powershell
rm utils/health_check.py
git checkout HEAD -- gui/main_window.py
```

---

## 📋 Phase 4: 监控与诊断（2天）⭐⭐⭐

### 任务 4.1：崩溃报告（1天）

**目标**：崩溃时自动生成诊断信息

**步骤**：

1. **创建崩溃报告生成器** `utils/crash_reporter.py`
```python
import sys
import traceback
import platform
import json
from pathlib import Path
from datetime import datetime

def generate_crash_report(exc_type, exc_value, exc_traceback):
    """生成崩溃报告"""
    report = {
        'timestamp': datetime.now().isoformat(),
        'version': '2.2.2',  # 从配置读取
        'platform': {
            'system': platform.system(),
            'release': platform.release(),
            'python': sys.version,
        },
        'exception': {
            'type': exc_type.__name__,
            'message': str(exc_value),
            'traceback': ''.join(traceback.format_exception(
                exc_type, exc_value, exc_traceback
            )),
        },
        'recent_logs': get_recent_logs(50),
    }
    
    # 保存报告
    report_dir = Path('crash_reports')
    report_dir.mkdir(exist_ok=True)
    
    report_path = report_dir / f'crash_{int(datetime.now().timestamp())}.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    return report_path

def get_recent_logs(lines=50):
    """获取最近的日志"""
    log_file = Path('logs/app.log')
    if not log_file.exists():
        return []
    
    with open(log_file, 'r', encoding='utf-8') as f:
        all_lines = f.readlines()
        return all_lines[-lines:]

def setup_crash_handler():
    """设置全局异常处理"""
    def exception_handler(exc_type, exc_value, exc_traceback):
        # 跳过键盘中断
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        # 记录日志
        from loguru import logger
        logger.critical(
            '未捕获异常',
            exc_info=(exc_type, exc_value, exc_traceback)
        )
        
        # 生成报告
        report_path = generate_crash_report(exc_type, exc_value, exc_traceback)
        
        # 显示错误对话框
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(
            None,
            '程序崩溃',
            f'程序遇到错误需要退出\n\n'
            f'诊断报告已保存至：\n{report_path}\n\n'
            f'请将此文件提交给开发者以帮助修复问题'
        )
    
    sys.excepthook = exception_handler
```

2. **集成到主程序** `main.py`
```python
from utils.crash_reporter import setup_crash_handler

# 尽早设置
setup_crash_handler()
```

3. **验收**
- [ ] 手动触发异常，检查是否生成报告
- [ ] 报告包含堆栈、日志等信息

**回滚方案**：
```powershell
rm utils/crash_reporter.py
git checkout HEAD -- main.py
```

---

### 任务 4.2：性能监控（1天）

**目标**：记录关键操作耗时

**步骤**：

1. **创建性能监控** `utils/performance.py`
```python
import time
from functools import wraps
from loguru import logger

def measure_time(operation_name):
    """测量函数执行时间的装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                elapsed = time.time() - start
                
                # 只记录慢操作
                if elapsed > 1.0:
                    logger.info(f'⏱️ {operation_name} 耗时 {elapsed:.2f}秒')
                
                return result
            except Exception as e:
                elapsed = time.time() - start
                logger.warning(f'⏱️ {operation_name} 失败，耗时 {elapsed:.2f}秒: {e}')
                raise
        return wrapper
    return decorator

# 使用示例
@measure_time('获取视频信息')
async def get_video_info(self, bvid):
    ...

@measure_time('发送评论')
async def post_comment(self, aid, text):
    ...
```

2. **应用到关键方法**
```python
# core/bilibili_api.py
from utils.performance import measure_time

@measure_time('搜索视频')
async def search_videos(self, keyword, count=20):
    ...

@measure_time('获取评论')
async def get_comments(self, aid, ...):
    ...
```

3. **验收**
- [ ] 日志中出现耗时记录
- [ ] 可以识别慢操作

**回滚方案**：
```powershell
rm utils/performance.py
git checkout HEAD -- core/bilibili_api.py
```

---

## 📊 总体时间表

| 阶段 | 任务 | 天数 | 开始日期 | 完成日期 |
|------|------|------|----------|----------|
| **Phase 1** | 紧急修复 | 3 | D1 | D3 |
| - | 异常处理清理 | 1 | D1 | D1 |
| - | 配置验证 | 1 | D2 | D2 |
| - | QThread防御 | 1 | D3 | D3 |
| **Phase 2** | 性能优化 | 5 | D4 | D8 |
| - | 简单缓存 | 2 | D4 | D5 |
| - | 日志异步化 | 2 | D6 | D7 |
| - | 批量API调用 | 1 | D8 | D8 |
| **Phase 3** | 用户体验 | 3 | D9 | D11 |
| - | 首次启动向导 | 2 | D9 | D10 |
| - | 健康检查 | 1 | D11 | D11 |
| **Phase 4** | 监控诊断 | 2 | D12 | D13 |
| - | 崩溃报告 | 1 | D12 | D12 |
| - | 性能监控 | 1 | D13 | D13 |

**总计：13 天**

---

## ✅ 每日检查清单

### 开始工作前
- [ ] 创建新分支 `git checkout -b opt-phase-X`
- [ ] 确认测试全部通过 `python -m pytest tests`
- [ ] 备份配置文件 `cp data/config.json data/config.json.bak`

### 完成任务后
- [ ] 运行测试 `python -m pytest tests -v`
- [ ] 手动测试核心流程
- [ ] 提交代码 `git commit -am "任务X.X: 描述"`
- [ ] 记录改动和效果

### 遇到问题时
- [ ] 不要强行推进，立即回滚
- [ ] 记录问题原因
- [ ] 寻求帮助或调整方案

---

## 🎯 预期收益（务实版）

### 性能指标
- API 调用量减少 40-50%（缓存）
- 日志写入不阻塞主线程（异步）
- 批量操作速度提升 3-5倍

### 稳定性指标
- 异常处理更精确（清理95处noqa）
- 窗口关闭不崩溃（QThread防御）
- 配置错误早发现（启动验证）

### 用户体验指标
- 新用户配置时间：从15分钟降至5分钟
- 问题自动检测（健康检查）
- 崩溃自动诊断（报告生成）

### 不承诺的指标
- ❌ 不保证启动速度提升60%（需要大改）
- ❌ 不保证内存降低30%（需要profiling）
- ❌ 不保证测试覆盖率80%（需要大量时间）

---

## 🔄 回滚策略

### Git分支管理
```bash
# 每个Phase独立分支
main
├── opt-phase-1-fixes      # 紧急修复
├── opt-phase-2-perf       # 性能优化
├── opt-phase-3-ux         # 用户体验
└── opt-phase-4-monitor    # 监控诊断

# 合并时使用 --no-ff 保留分支历史
git merge --no-ff opt-phase-1-fixes
```

### 任务级回滚
```bash
# 回滚单个任务
git log --oneline  # 找到任务提交的hash
git revert <commit-hash>

# 回滚整个文件
git checkout HEAD~1 -- path/to/file.py
```

### 紧急回滚
```bash
# 回到最后一个稳定版本
git tag stable-before-optimization
git reset --hard stable-before-optimization
```

---

## 💡 注意事项

### ⚠️ 不要做的事
1. **不要同时改多个Phase** - 一次只做一个阶段
2. **不要跳过测试** - 每次改动必须跑测试
3. **不要改动核心逻辑** - 只优化，不重构
4. **不要引入新的大依赖** - Redis、Celery等都不要
5. **不要在生产环境直接改** - 用测试环境验证

### ✅ 务必做的事
1. **小步快跑** - 每个任务独立完成和验证
2. **保留日志** - 记录每次改动和效果
3. **及时回滚** - 发现问题立即回退
4. **保持备份** - 重要文件改动前备份
5. **寻求帮助** - 遇到困难及时沟通

---

## 📞 需要帮助？

**遇到以下情况请暂停：**
- 测试失败超过3次
- 改动导致程序无法启动
- 不确定某个改动是否安全
- 需要改动超过5个文件

**获取帮助：**
1. 记录当前状态（git status, 错误日志）
2. 回滚到最近的稳定状态
3. 描述问题和已尝试的方案
4. 寻求代码审查

---

## 📝 改动记录模板

```markdown
### 任务 X.X: [任务名称]

**日期**: 2026-10-28
**耗时**: X 小时
**状态**: ✅完成 / ⚠️部分完成 / ❌失败

**改动文件**:
- core/xxx.py: [改动说明]
- utils/xxx.py: [改动说明]

**测试结果**:
- 单元测试: 112/112 通过
- 手动测试: [测试步骤和结果]

**效果评估**:
- [指标1]: 从 X 提升至 Y
- [指标2]: 从 X 降低至 Y

**遇到的问题**:
- [问题1及解决方案]
- [问题2及解决方案]

**下一步**:
- [ ] 待办事项1
- [ ] 待办事项2
```

---

## 🎉 完成标准

### Phase 1 完成标准
- [ ] 95处异常中至少修复20处最危险的
- [ ] 配置验证正常工作
- [ ] 窗口关闭不再崩溃
- [ ] 所有测试通过

### Phase 2 完成标准
- [ ] 缓存命中率 > 40%
- [ ] 日志写入不阻塞主线程
- [ ] 批量操作明显变快
- [ ] 所有测试通过

### Phase 3 完成标准
- [ ] 新用户可以通过向导完成配置
- [ ] 健康检查每分钟运行一次
- [ ] 常见问题自动提示
- [ ] 所有测试通过

### Phase 4 完成标准
- [ ] 崩溃时自动生成报告
- [ ] 慢操作有耗时记录
- [ ] 所有测试通过

### 最终验收
- [ ] **所有112个测试通过**
- [ ] **手动完整流程无异常**
- [ ] **性能至少提升20%**
- [ ] **稳定性明显改善**
- [ ] **用户体验有提升**

---

**现在可以开始执行了！建议从 Phase 1 的任务 1.1 开始。**
