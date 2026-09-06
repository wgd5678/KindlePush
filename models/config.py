# -*- coding: utf-8 -*-
"""配置数据模型与持久化（SRS 3.6）."""
import json
import logging
import os
import tempfile
from dataclasses import dataclass

logger = logging.getLogger('kindle_push.config')


@dataclass
class EmailConfig:
    """邮件推送配置."""

    sender_email: str = ''
    smtp_server: str = ''
    smtp_port: int = 587
    password: str = ''          # 内存中为明文，落盘时加密
    kindle_email: str = ''

    def is_complete(self) -> bool:
        return not self.missing_items()

    def missing_items(self) -> list:
        missing = []
        if not self.sender_email:
            missing.append('发件邮箱')
        if not self.smtp_server:
            missing.append('SMTP服务器')
        if not self.smtp_port:
            missing.append('SMTP端口')
        if not self.password:
            missing.append('密码/授权码')
        if not self.kindle_email:
            missing.append('Kindle邮箱')
        return missing


@dataclass
class ApiConfig:
    """API 推送配置."""

    oauth_state_saved: bool = False
    last_device_serial: str = ''


@dataclass
class GeneralConfig:
    """通用设置."""

    default_format: str = 'KFX'
    auto_delete_temp: bool = False
    size_warning: bool = True
    size_warning_threshold: int = 50      # MB
    log_keep_days: int = 30
    remember_push_method: bool = True
    last_push_method: str = 'email'
    convert_push: bool = True             # 邮件推送是否触发亚马逊云端转换


class AppConfig:
    """应用配置，JSON 存储，敏感字段加密."""

    def __init__(self, config_path: str, crypto):
        self.config_path = config_path
        self.crypto = crypto
        self.email = EmailConfig()
        self.api = ApiConfig()
        self.general = GeneralConfig()

    def load(self) -> bool:
        if not os.path.exists(self.config_path):
            return False
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.error('配置文件读取失败: %s', e)
            return False

        email = raw.get('email', {})
        self.email.sender_email = email.get('sender_email', '')
        self.email.smtp_server = email.get('smtp_server', '')
        try:
            self.email.smtp_port = int(email.get('smtp_port', 587) or 587)
        except (TypeError, ValueError):
            self.email.smtp_port = 587
        self.email.password = self.crypto.decrypt(email.get('password_encrypted', ''))
        self.email.kindle_email = email.get('kindle_email', '')

        api = raw.get('api', {})
        self.api.oauth_state_saved = bool(api.get('oauth_state'))
        self.api.last_device_serial = api.get('last_device_serial', '')

        g = raw.get('general', {})
        self.general.default_format = g.get('default_format', 'KFX')
        self.general.auto_delete_temp = bool(g.get('auto_delete_temp', False))
        self.general.size_warning = bool(g.get('size_warning', True))
        try:
            self.general.size_warning_threshold = int(g.get('size_warning_threshold', 50))
        except (TypeError, ValueError):
            self.general.size_warning_threshold = 50
        try:
            self.general.log_keep_days = int(g.get('log_keep_days', 30))
        except (TypeError, ValueError):
            self.general.log_keep_days = 30
        self.general.remember_push_method = bool(g.get('remember_push_method', True))
        self.general.last_push_method = g.get('last_push_method', 'email')
        self.general.convert_push = bool(g.get('convert_push', True))
        return True

    def save(self) -> bool:
        data = {
            'email': {
                'sender_email': self.email.sender_email,
                'smtp_server': self.email.smtp_server,
                'smtp_port': self.email.smtp_port,
                'password_encrypted': self.crypto.encrypt(self.email.password),
                'kindle_email': self.email.kindle_email,
            },
            'api': {
                'oauth_state': 'client_state_saved' if self.api.oauth_state_saved else '',
                'last_device_serial': self.api.last_device_serial,
            },
            'general': {
                'default_format': self.general.default_format,
                'auto_delete_temp': self.general.auto_delete_temp,
                'size_warning': self.general.size_warning,
                'size_warning_threshold': self.general.size_warning_threshold,
                'log_keep_days': self.general.log_keep_days,
                'remember_push_method': self.general.remember_push_method,
                'last_push_method': self.general.last_push_method,
                'convert_push': self.general.convert_push,
            },
        }
        # 原子写入：先写临时文件再替换，避免中途失败损坏配置
        dir_name = os.path.dirname(self.config_path) or '.'
        try:
            fd, tmp_path = tempfile.mkstemp(prefix='.config_', suffix='.tmp', dir=dir_name)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.config_path)
            try:
                os.chmod(self.config_path, 0o600)
            except OSError:
                pass
            return True
        except OSError as e:
            logger.error('配置保存失败: %s', e)
            return False
