"""B 站登录、凭据保存与账号信息。

从 ``core.bilibili_api`` 拆出的登录相关逻辑，配合其他 mixin 组成 BilibiliAPI。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from bilibili_api import Credential, login_v2, user
from loguru import logger

from utils import secure_store

_CREDENTIAL_FIELDS = (
    'SESSDATA', 'bili_jct', 'buvid3', 'buvid4', 'dedeuserid', 'ac_time_value',
)


class BiliAuthMixin:
    """二维码登录、Cookie 持久化、登录状态检查。"""

    def _load_credential(self):
        """从文件加载凭证；旧版本明文 Cookie 会自动加密迁移。"""
        if not self.credential_path.exists():
            return
        try:
            with open(self.credential_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            plain = {
                key: (data.get(key) or '') for key in _CREDENTIAL_FIELDS
            }
            # 兼容旧字段名
            plain['dedeuserid'] = plain['dedeuserid'] or str(
                data.get('DedeUserID') or ''
            )
            values = {
                key: secure_store.unprotect(value)
                for key, value in plain.items()
            }
            self.credential = Credential(
                sessdata=values['SESSDATA'],
                bili_jct=values['bili_jct'],
                buvid3=values['buvid3'],
                buvid4=values['buvid4'] or None,
                dedeuserid=values['dedeuserid'] or None,
                ac_time_value=values['ac_time_value'] or None,
            )
            logger.info("已加载B站登录凭证")
            if secure_store.available() and any(
                value and not secure_store.is_encrypted(value)
                for value in plain.values()
            ):
                # 把遗留的明文 Cookie 立即转成密文
                self._save_credential(
                    values['SESSDATA'], values['bili_jct'], values['buvid3'],
                    values['buvid4'], values['dedeuserid'],
                    values['ac_time_value'],
                )
                logger.info("已将明文登录凭证迁移为加密存储")
        except Exception as e:
            logger.warning(f"加载凭证失败: {e}")
            self.credential = None

    def _save_credential(
        self,
        sessdata: str,
        bili_jct: str,
        buvid3: str,
        buvid4: str = '',
        dedeuserid: str = '',
        ac_time_value: str = '',
    ):
        """保存凭证到文件（敏感字段加密）。"""
        self.credential_path = Path(self.credential_path)
        self.credential_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'SESSDATA': secure_store.protect(sessdata),
            'bili_jct': secure_store.protect(bili_jct),
            'buvid3': secure_store.protect(buvid3),
            'buvid4': secure_store.protect(buvid4),
            'dedeuserid': secure_store.protect(dedeuserid),
            'ac_time_value': secure_store.protect(ac_time_value),
            'saved_at': datetime.now().isoformat(),
        }
        with open(self.credential_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self.credential = Credential(
            sessdata=sessdata,
            bili_jct=bili_jct,
            buvid3=buvid3,
            buvid4=buvid4 or None,
            dedeuserid=dedeuserid or None,
            ac_time_value=ac_time_value or None,
        )
        self._self_info = None
        logger.info("凭证已保存")

    def _remember_credential(self, credential: Credential) -> None:
        """把 QR 登录返回的 Credential 落盘。"""
        self._save_credential(
            credential.sessdata or '',
            credential.bili_jct or '',
            credential.buvid3 or '',
            credential.buvid4 or '',
            credential.dedeuserid or '',
            credential.ac_time_value or '',
        )

    async def login_with_qr(self) -> tuple[bool, Optional[bytes], Optional[Any]]:
        """生成登录二维码。

        Returns:
            (成功状态, 二维码图片字节, QrCodeLogin 对象)
        """
        try:
            if not hasattr(login_v2.QrCodeLogin, 'check_state'):
                raise RuntimeError(
                    'bilibili-api 版本过旧，请安装 requirements.txt 中锁定的版本'
                )
            qr_login = login_v2.QrCodeLogin()

            # 生成二维码（异步方法）
            await qr_login.generate_qrcode()

            qr_picture = qr_login.get_qrcode_picture()
            if not qr_picture:
                logger.error("无法获取二维码图片")
                return False, None, None

            logger.info("二维码已生成，等待扫描...")
            return True, qr_picture.content, qr_login
        except Exception as e:
            logger.error(f"生成二维码失败: {e}")
            return False, None, None

    async def check_qr_status(self, qr_login: Any) -> Dict[str, Any]:
        """用官方 API 查询扫码状态，避免依赖私有属性。"""
        try:
            from bilibili_api.login_v2 import QrCodeLoginEvents

            state = await qr_login.check_state()
            if state == QrCodeLoginEvents.DONE or qr_login.has_done():
                credential = qr_login.get_credential()
                self._remember_credential(credential)
                logger.info("登录成功，凭证已保存")
                return {'status': 'success', 'credential': credential}
            if state == QrCodeLoginEvents.TIMEOUT:
                return {'status': 'expired', 'message': '二维码已过期'}
            if state == QrCodeLoginEvents.CONF:
                return {'status': 'waiting', 'scanned': True}
            return {'status': 'waiting', 'scanned': False}
        except Exception as e:
            logger.error(f"检查二维码状态失败: {e}")
            return {'status': 'error', 'message': str(e)}

    async def get_self_info(self) -> Dict[str, Any]:
        """获取当前登录账号的 uid 和昵称（缓存）。"""
        if self._self_info is not None:
            return self._self_info
        if not self.credential:
            return {}
        try:
            info = await user.get_self_info(self.credential)
            self._self_info = {
                'uid': info.get('mid'),
                'name': info.get('name') or '',
            }
        except Exception as exc:
            logger.debug(f"获取登录账号信息失败: {exc}")
            self._self_info = {}
        return self._self_info

    async def check_login(self) -> bool:
        """检查登录状态。"""
        if not self.credential:
            return False
        try:
            # 老版本 cookies 可能没有 buvid4，补一个可降低 412 概率。
            if not getattr(self.credential, 'buvid4', None):
                try:
                    from bilibili_api.utils.network import get_buvid
                    _, buvid4 = await get_buvid()
                    if buvid4:
                        self.credential.buvid4 = buvid4
                        self._remember_credential(self.credential)
                        logger.info("已补充 buvid4 风控参数")
                except (AttributeError, TypeError, ValueError) as exc:
                    logger.debug(f"补充 buvid4 失败: {exc}")
            info = await user.get_self_info(credential=self.credential)
            if not isinstance(info, dict) or not info.get('name'):
                logger.warning("登录状态检查失败: 未获取到用户信息")
                return False
            logger.info(f"登录有效，用户: {info.get('name')}")
            return True
        except Exception as e:
            logger.warning(f"登录状态检查失败: {e}")
            return False
