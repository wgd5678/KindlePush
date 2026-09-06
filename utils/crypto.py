# -*- coding: utf-8 -*-
"""加密工具：邮箱密码等敏感字段加密存储（SRS 3.6 安全要求）.

采用 cryptography 库的 Fernet 对称加密，密钥文件与配置文件同目录，
文件权限设置为仅当前用户可读写（0600，Windows 下尽力而为）。
"""
import binascii
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger('kindle_push.crypto')


class CryptoStore:
    """基于本地密钥文件的加解密存储."""

    def __init__(self, key_path: str):
        self.key_path = key_path
        self._fernet = None

    def _get_fernet(self) -> Fernet:
        if self._fernet is None:
            key = None
            if os.path.exists(self.key_path):
                try:
                    with open(self.key_path, 'rb') as f:
                        key = f.read().strip()
                except OSError as e:
                    logger.warning('密钥文件读取失败: %s', e)
            if not key:
                key = Fernet.generate_key()
                try:
                    os.makedirs(os.path.dirname(self.key_path), exist_ok=True)
                    with open(self.key_path, 'wb') as f:
                        f.write(key)
                    os.chmod(self.key_path, 0o600)
                except OSError as e:
                    logger.warning('密钥文件写入失败: %s', e)
            self._fernet = Fernet(key)
        return self._fernet

    def encrypt(self, plaintext: str) -> str:
        """加密明文字符串，返回 base64 文本；空输入返回空串."""
        if not plaintext:
            return ''
        return self._get_fernet().encrypt(plaintext.encode('utf-8')).decode('ascii')

    def decrypt(self, token: str) -> str:
        """解密密文；失败或空输入返回空串."""
        if not token:
            return ''
        try:
            return self._get_fernet().decrypt(token.encode('ascii')).decode('utf-8')
        except (InvalidToken, ValueError, binascii.Error, OSError) as e:
            logger.warning('解密失败（密钥不匹配或密文损坏）: %s', e)
            return ''
