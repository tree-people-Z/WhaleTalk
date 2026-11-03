"""在磁盘上保护敏感字符串（Windows DPAPI，用户级加密）。

配置文件里的 API Key、B 站 Cookie 都属于"拿到就能冒用身份"的凭据。
本模块用 Windows 自带的 DPAPI 以当前用户身份加密，写盘时是密文，
只有同一台机器上的同一 Windows 用户能解密。

非 Windows 平台或加密失败时自动退回明文，保证程序仍可运行。
"""

import base64
import ctypes
import sys
from ctypes import wintypes
from typing import Optional

from loguru import logger

PREFIX = 'dpapi:'
# 附加熵，避免同机其他程序直接解密本程序的数据。
_ENTROPY = b'WhaleTalk/credential/v1'
_CRYPTPROTECT_UI_FORBIDDEN = 0x1

if sys.platform == 'win32':  # pragma: no branch - platform guard
    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ('cbData', wintypes.DWORD),
            ('pbData', ctypes.POINTER(ctypes.c_char)),
        ]

    _crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), wintypes.LPCWSTR,
        ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
    ]
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
    ]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    _kernel32.LocalFree.restype = wintypes.HLOCAL

    def _blob(data: bytes):
        buffer = ctypes.create_string_buffer(data, len(data))
        blob = _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
        return blob, buffer


def available() -> bool:
    """当前环境是否支持加密存储。"""
    return sys.platform == 'win32'


def is_encrypted(value: object) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def protect(value: Optional[str]) -> str:
    """把明文加密成 ``dpapi:...``；不可用时原样返回。"""
    if not value or not isinstance(value, str) or is_encrypted(value):
        return value or ''
    if not available():
        return value
    try:
        data_in, keep_in = _blob(value.encode('utf-8'))
        entropy, keep_entropy = _blob(_ENTROPY)
        data_out = _DATA_BLOB()
        ok = _crypt32.CryptProtectData(
            ctypes.byref(data_in), None, ctypes.byref(entropy),
            None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(data_out),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            raw = ctypes.string_at(data_out.pbData, data_out.cbData)
        finally:
            _kernel32.LocalFree(ctypes.cast(data_out.pbData, wintypes.HLOCAL))
        return PREFIX + base64.b64encode(raw).decode('ascii')
    except Exception as exc:  # noqa: BLE001
        logger.warning(f'凭据加密失败，将退回明文存储: {exc}')
        return value


def unprotect(value: Optional[str]) -> str:
    """解密 ``dpapi:...``；明文原样返回；解密失败返回空串。"""
    if not value or not isinstance(value, str):
        return ''
    if not is_encrypted(value):
        return value
    if not available():
        logger.warning('当前系统不支持 DPAPI，无法解密已加密的凭据')
        return ''
    try:
        raw = base64.b64decode(value[len(PREFIX):])
        data_in, keep_in = _blob(raw)
        entropy, keep_entropy = _blob(_ENTROPY)
        data_out = _DATA_BLOB()
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(data_in), None, ctypes.byref(entropy),
            None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(data_out),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            plain = ctypes.string_at(data_out.pbData, data_out.cbData)
        finally:
            _kernel32.LocalFree(ctypes.cast(data_out.pbData, wintypes.HLOCAL))
        return plain.decode('utf-8')
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            '凭据解密失败（可能换过 Windows 用户或迁移过 data 目录），'
            f'请在设置中重新填写: {exc}'
        )
        return ''
