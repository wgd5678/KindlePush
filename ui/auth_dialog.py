# -*- coding: utf-8 -*-
"""API 授权对话框（SRS 4.3）：打开亚马逊授权页 → 粘贴回跳 URL → 完成授权."""
import logging
import webbrowser

from PyQt5.QtCore import QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QVBoxLayout)

from core.api_client import INSTALL_HINT, STKCLIENT_AVAILABLE

logger = logging.getLogger('kindle_push.ui.auth')

STEP_TEXT = (
    '请按以下步骤完成授权：\n\n'
    '步骤 1：点击下方按钮，在浏览器中打开授权页面。\n'
    '步骤 2：登录亚马逊账号并完成授权。\n'
    '步骤 3：授权成功后，复制浏览器地址栏中的完整 URL，粘贴到下方并点击「确认授权」。'
)


class _SigninUrlThread(QThread):
    url_ready = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, api_client, parent=None):
        super().__init__(parent)
        self.api_client = api_client

    def run(self):
        try:
            self.url_ready.emit(self.api_client.authorize())
        except Exception as e:
            self.failed.emit(str(e))


class _FinishAuthThread(QThread):
    done = pyqtSignal(bool, str)

    def __init__(self, api_client, redirect_url, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.redirect_url = redirect_url

    def run(self):
        try:
            ok = self.api_client.finish_authorization(self.redirect_url)
            self.done.emit(ok, '' if ok else '无法从该 URL 完成授权，请重新复制完整地址')
        except Exception as e:
            self.done.emit(False, str(e))


class AuthDialog(QDialog):
    """亚马逊账号 OAuth 授权对话框."""

    def __init__(self, parent, api_client):
        super().__init__(parent)
        self.api_client = api_client
        self._thread = None
        self.setWindowTitle('亚马逊账号授权')
        self.setMinimumWidth(560)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(QLabel(STEP_TEXT))

        self.btn_open = QPushButton('🌐 打开亚马逊授权页面')
        self.btn_open.clicked.connect(self._on_open)
        layout.addWidget(self.btn_open)

        self.edt_url = QLineEdit()
        self.edt_url.setPlaceholderText('https://www.amazon.com/ap/oa?...')
        layout.addWidget(self.edt_url)

        btn_row = QHBoxLayout()
        self.btn_confirm = QPushButton('✅ 确认授权')
        self.btn_confirm.setObjectName('primaryBtn')
        self.btn_confirm.clicked.connect(self._on_confirm)
        self.btn_cancel = QPushButton('❌ 取消')
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_confirm)
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)

        self.lbl_status = QLabel('')
        self.lbl_status.setObjectName('hintLabel')
        layout.addWidget(self.lbl_status)

    # ---------- events ----------

    def _on_open(self):
        if not STKCLIENT_AVAILABLE:
            QMessageBox.warning(self, '依赖缺失', INSTALL_HINT)
            return
        self.lbl_status.setText('正在生成授权链接…')
        self.btn_open.setEnabled(False)
        self._thread = _SigninUrlThread(self.api_client, self)
        self._thread.url_ready.connect(self._on_url_ready)
        self._thread.failed.connect(self._on_url_failed)
        self._thread.start()

    def _on_url_ready(self, url: str):
        self.btn_open.setEnabled(True)
        self.lbl_status.setText('⏳ 等待授权… 请在浏览器中登录，完成后复制地址栏 URL 粘贴到上方')
        try:
            webbrowser.open(url)
        except Exception as e:
            self.edt_url.setText(url)
            QMessageBox.information(self, '无法自动打开浏览器',
                                    '请手动复制以下链接到浏览器打开：\n%s\n(%s)' % (url, e))

    def _on_url_failed(self, error: str):
        self.btn_open.setEnabled(True)
        self.lbl_status.setText('生成授权链接失败：%s' % error)
        QMessageBox.critical(self, '授权失败', '生成授权链接失败：\n%s' % error)

    def _on_confirm(self):
        url = self.edt_url.text().strip()
        if not url:
            QMessageBox.warning(self, '提示', '请先粘贴浏览器地址栏中的完整跳转 URL')
            return
        self.btn_confirm.setEnabled(False)
        self.lbl_status.setText('正在完成授权…')
        self._thread = _FinishAuthThread(self.api_client, url, self)
        self._thread.done.connect(self._on_finish_done)
        self._thread.start()

    def _on_finish_done(self, ok: bool, error: str):
        self.btn_confirm.setEnabled(True)
        if ok:
            self.lbl_status.setText('✅ 授权成功')
            logger.info('用户完成亚马逊账号授权')
            QTimer.singleShot(600, self.accept)
        else:
            self.lbl_status.setText('授权失败：%s' % error)
            QMessageBox.critical(self, '授权失败', error or '授权失败，请重试')
