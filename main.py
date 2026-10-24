#!/usr/bin/env python3
"""
鲸语 - B站智能运营助手
主入口文件
"""

import sys
import os
from pathlib import Path

# The bootstrap uses only the standard library and runs before PyQt/app imports.
PROJECT_ROOT = Path(__file__).parent
if getattr(sys, 'frozen', False):
    # Keep user data beside the downloaded executable, outside PyInstaller's temp extraction.
    os.chdir(Path(sys.executable).resolve().parent)
    if os.name == 'nt':
        # PyQt's DLLs are nested below _internal; retain directory handles for Windows DLL lookup.
        _DLL_DIRECTORY_HANDLES = []
        for dll_dir in (
            Path(getattr(sys, '_MEIPASS', PROJECT_ROOT)) / 'PyQt6' / 'Qt6' / 'bin',
            Path(getattr(sys, '_MEIPASS', PROJECT_ROOT)),
        ):
            if dll_dir.is_dir():
                _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(dll_dir)))
sys.path.insert(0, str(PROJECT_ROOT))
from utils.dependency_bootstrap import ensure_required_dependencies

try:
    ensure_required_dependencies()
except Exception as exc:
    # Windowed builds have no stderr; avoid turning a startup error into a crash.
    if sys.stderr is not None:
        print(f"依赖准备失败: {exc}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def _transcription_self_check(argv) -> int:
    """Diagnostic entry point for the portable transcription component."""
    log_dir = Path('data/logs')
    log_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    try:
        from utils.transcription_component import (
            component_info, configure_hf_endpoint, ensure_importable,
        )
        lines.append(f'component_info={component_info()}')
        lines.append(f'importable={ensure_importable()}')
        lines.append(f'hf_endpoint={configure_hf_endpoint()}')
        import av
        import ctranslate2
        import faster_whisper
        import numpy
        lines.append(f'faster_whisper={getattr(faster_whisper, "__version__", "?")}')
        lines.append(f'ctranslate2={getattr(ctranslate2, "__version__", "?")}')
        lines.append(f'av={getattr(av, "__version__", "?")}')
        lines.append(f'numpy={numpy.__version__}')
        model_name = 'tiny'
        if '--model' in argv:
            model_index = argv.index('--model')
            if model_index + 1 < len(argv) and not argv[model_index + 1].startswith('--'):
                model_name = argv[model_index + 1]
        from core.audio_transcriber import LocalAudioTranscriber
        manual_model = LocalAudioTranscriber.local_model_path(
            Path('data/models/faster-whisper'), model_name
        )
        lines.append(f'manual_model_path={manual_model}')
        model_argument = manual_model or model_name
        if '--download-model' in argv:
            from faster_whisper import WhisperModel
            WhisperModel(
                model_argument,
                device='cpu',
                compute_type='int8',
                download_root='data/models/faster-whisper',
            )
            lines.append(f'model_ready={model_name}')
        if '--transcribe-wav' in argv:
            wav_index = argv.index('--transcribe-wav')
            if wav_index + 1 >= len(argv):
                raise RuntimeError('--transcribe-wav 需要一个 WAV 文件路径')
            wav_path = argv[wav_index + 1]
            import wave

            import numpy as np
            from faster_whisper import WhisperModel
            model = WhisperModel(
                model_argument,
                device='cpu',
                compute_type='int8',
                download_root='data/models/faster-whisper',
            )
            with wave.open(wav_path, 'rb') as handle:
                frames = handle.readframes(handle.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            segments, info = model.transcribe(
                audio, beam_size=3, vad_filter=True,
                condition_on_previous_text=False,
            )
            text = ' '.join(
                segment.text.strip() for segment in segments if segment.text.strip()
            )
            lines.append(f'transcript_language={getattr(info, "language", "?")}')
            lines.append(f'transcript={text}')
        lines.append('RESULT=OK')
    except Exception as exc:  # noqa: BLE001
        import traceback
        lines.append(f'RESULT=ERROR: {exc}')
        lines.append(traceback.format_exc())
    (log_dir / 'transcription-selfcheck.log').write_text(
        '\n'.join(lines), encoding='utf-8'
    )
    return 0


if '--transcription-self-test' in sys.argv:
    sys.exit(_transcription_self_check(sys.argv))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from gui.main_window import MainWindow
from utils.logger import setup_logger
from utils.config_manager import ConfigManager
from utils.ffmpeg_bootstrap import ensure_ffmpeg
from utils.persona_defaults import ensure_default_persona


def main():
    """程序主入口"""
    # 初始化日志
    logger = setup_logger()
    logger.info("=" * 60)
    logger.info("鲸语 · B站智能运营助手启动")
    logger.info("=" * 60)

    # 单文件版：首次启动解压内置 ffmpeg
    ensure_ffmpeg()

    # 初始化配置
    config_manager = ConfigManager()
    if not config_manager.config_file.exists():
        logger.info("首次运行，创建默认配置文件")
        config_manager.create_default_config()

    # 首次启动释放打包的默认人设；已有 data/persona.md 时不会覆盖。
    ensure_default_persona(config_manager.get('persona.persona_file', 'data/persona.md'))

    # 创建应用
    app = QApplication(sys.argv)
    app.setApplicationName("鲸语")
    icon_path = PROJECT_ROOT / "assets" / "whale-assistant.ico"
    if icon_path.exists():
        from PyQt6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyle("Fusion")  # 使用Fusion风格

    # 设置高DPI支持
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    # 创建主窗口
    main_window = MainWindow()
    main_window.show()

    logger.info("主窗口已显示")

    # 运行应用
    exit_code = app.exec()

    logger.info(f"程序退出，退出码: {exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
