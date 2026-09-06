# -*- coding: utf-8 -*-
"""UI 层共用的后台线程：设备列表加载、SMTP 连接测试."""
import smtplib
import ssl

from PyQt5.QtCore import QThread, pyqtSignal


class LoadDevicesThread(QThread):
    """后台获取亚马逊账号下的 Kindle 设备列表."""

    loaded = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, api_client, parent=None):
        super().__init__(parent)
        self.api_client = api_client

    def run(self):
        try:
            self.loaded.emit(self.api_client.get_devices())
        except Exception as e:
            self.failed.emit(str(e))


class SmtpTestThread(QThread):
    """后台测试 SMTP 连接与认证."""

    finished_test = pyqtSignal(bool, str)

    def __init__(self, server: str, port: int, user: str, password: str, parent=None):
        super().__init__(parent)
        self.server = server
        self.port = port
        self.user = user
        self.password = password

    def run(self):
        smtp = None
        try:
            context = ssl.create_default_context()
            if self.port == 465:
                smtp = smtplib.SMTP_SSL(self.server, self.port, timeout=15,
                                        context=context)
            else:
                smtp = smtplib.SMTP(self.server, self.port, timeout=15)
                smtp.starttls(context=context)
            smtp.login(self.user, self.password)
            self.finished_test.emit(True, '连接成功，认证通过')
        except smtplib.SMTPAuthenticationError:
            self.finished_test.emit(False, '邮箱认证失败，请检查密码/授权码')
        except Exception as e:
            self.finished_test.emit(False, '邮件服务器连接失败: %s' % e)
        finally:
            if smtp is not None:
                try:
                    smtp.quit()
                except Exception:
                    pass
