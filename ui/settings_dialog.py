# -*- coding: utf-8 -*-
"""设置对话框（SRS 4.2）：邮箱配置 / API 授权 / 通用设置."""
import logging
import os
import shutil

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog,
                             QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QMessageBox, QPushButton, QSpinBox,
                             QVBoxLayout, QWidget)

from core.api_client import INSTALL_HINT, STKCLIENT_AVAILABLE
from ui.auth_dialog import AuthDialog
from ui.common import LoadDevicesThread, SmtpTestThread

logger = logging.getLogger('kindle_push.ui.settings')

SMTP_PRESETS = {
    'gmail.com': ('smtp.gmail.com', 587),
    'qq.com': ('smtp.qq.com', 465),
    '163.com': ('smtp.163.com', 465),
    '126.com': ('smtp.126.com', 465),
    'outlook.com': ('smtp.office365.com', 587),
    'hotmail.com': ('smtp.office365.com', 587),
}


class SettingsDialog(QDialog):
    """设置窗口：邮件配置、API 授权、通用设置."""

    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.ctx = ctx
        self._thread = None
        self.setWindowTitle('设置')
        self.setMinimumWidth(600)
        self._build_ui()
        self._refresh_auth_ui()

    # ---------- UI ----------

    def _build_ui(self):
        cfg = self.ctx.config
        root = QVBoxLayout(self)
        root.setSpacing(12)

        # 邮件推送配置
        g_email = QGroupBox('📧 邮件推送配置')
        form = QFormLayout(g_email)
        form.setLabelAlignment(Qt.AlignRight)

        self.edt_sender = QLineEdit(cfg.email.sender_email)
        self.edt_sender.setPlaceholderText('user@gmail.com')
        self.edt_sender.editingFinished.connect(self._on_sender_edited)
        form.addRow('发件邮箱:', self.edt_sender)

        smtp_row = QHBoxLayout()
        self.edt_smtp = QLineEdit(cfg.email.smtp_server)
        self.edt_smtp.setPlaceholderText('smtp.gmail.com')
        smtp_row.addWidget(self.edt_smtp, 1)
        smtp_row.addWidget(QLabel('端口:'))
        self.spn_port = QSpinBox()
        self.spn_port.setRange(1, 65535)
        self.spn_port.setValue(cfg.email.smtp_port)
        smtp_row.addWidget(self.spn_port)
        form.addRow('SMTP服务器:', smtp_row)

        pwd_row = QHBoxLayout()
        self.edt_password = QLineEdit(cfg.email.password)
        self.edt_password.setEchoMode(QLineEdit.Password)
        pwd_row.addWidget(self.edt_password, 1)
        self.chk_show_pwd = QCheckBox('显示')
        self.chk_show_pwd.toggled.connect(self._on_toggle_pwd)
        pwd_row.addWidget(self.chk_show_pwd)
        self.btn_test = QPushButton('✅ 测试连接')
        self.btn_test.clicked.connect(self._on_test_connection)
        pwd_row.addWidget(self.btn_test)
        form.addRow('密码/授权码:', pwd_row)

        self.edt_kindle = QLineEdit(cfg.email.kindle_email)
        self.edt_kindle.setPlaceholderText('username@kindle.cn')
        form.addRow('Kindle邮箱:', self.edt_kindle)

        hint = QLabel('📌 提示: 需将发件邮箱添加到亚马逊「已批准的个人文档邮件列表」中；'
                      '邮件主题将自动设置为 Convert 以触发云端转换。')
        hint.setObjectName('hintLabel')
        hint.setWordWrap(True)
        form.addRow('', hint)
        root.addWidget(g_email)

        # API 推送配置
        g_api = QGroupBox('🔑 API推送配置')
        api_form = QFormLayout(g_api)
        auth_row = QHBoxLayout()
        self.lbl_auth_status = QLabel('❌ 未授权')
        auth_row.addWidget(self.lbl_auth_status)
        self.btn_auth = QPushButton('🔄 重新授权')
        self.btn_auth.clicked.connect(self._on_authorize)
        auth_row.addWidget(self.btn_auth)
        auth_row.addStretch(1)
        api_form.addRow('授权状态:', auth_row)

        dev_row = QHBoxLayout()
        self.cmb_device = QComboBox()
        dev_row.addWidget(self.cmb_device, 1)
        self.btn_refresh_devices = QPushButton('刷新')
        self.btn_refresh_devices.setObjectName('miniBtn')
        self.btn_refresh_devices.clicked.connect(self._on_refresh_devices)
        dev_row.addWidget(self.btn_refresh_devices)
        api_form.addRow('默认设备:', dev_row)
        if not STKCLIENT_AVAILABLE:
            hint_api = QLabel('⚠ %s' % INSTALL_HINT)
            hint_api.setObjectName('hintLabel')
            api_form.addRow('', hint_api)
        root.addWidget(g_api)

        # 通用设置
        g_general = QGroupBox('⚙️ 通用设置')
        gen_layout = QVBoxLayout(g_general)
        self.chk_auto_delete = QCheckBox('推送成功自动删除本地临时文件')
        self.chk_auto_delete.setChecked(cfg.general.auto_delete_temp)
        self.chk_size_warning = QCheckBox('推送前检查文件大小（邮件推送超限时拦截）')
        self.chk_size_warning.setChecked(cfg.general.size_warning)
        self.chk_remember = QCheckBox('记住上次使用的推送方式')
        self.chk_remember.setChecked(cfg.general.remember_push_method)
        gen_layout.addWidget(self.chk_auto_delete)
        gen_layout.addWidget(self.chk_size_warning)
        gen_layout.addWidget(self.chk_remember)

        limit_row = QHBoxLayout()
        limit_row.addWidget(QLabel('邮件推送大小上限:'))
        self.spn_threshold = QSpinBox()
        self.spn_threshold.setRange(1, 50)
        self.spn_threshold.setValue(cfg.general.size_warning_threshold)
        self.spn_threshold.setSuffix(' MB')
        limit_row.addWidget(self.spn_threshold)
        limit_row.addSpacing(24)
        limit_row.addWidget(QLabel('日志保留天数:'))
        self.spn_keep_days = QSpinBox()
        self.spn_keep_days.setRange(1, 365)
        self.spn_keep_days.setValue(cfg.general.log_keep_days)
        self.spn_keep_days.setSuffix(' 天')
        limit_row.addWidget(self.spn_keep_days)
        limit_row.addStretch(1)
        gen_layout.addLayout(limit_row)
        root.addWidget(g_general)

        # 底部按钮
        btn_row = QHBoxLayout()
        self.btn_save = QPushButton('💾 保存设置')
        self.btn_save.setObjectName('primaryBtn')
        self.btn_save.clicked.connect(self._on_save)
        self.btn_reset = QPushButton('↩️ 恢复默认')
        self.btn_reset.clicked.connect(self._on_reset)
        self.btn_export = QPushButton('📋 导出配置')
        self.btn_export.clicked.connect(self._on_export_config)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_save)
        btn_row.addWidget(self.btn_reset)
        btn_row.addWidget(self.btn_export)
        root.addLayout(btn_row)

    # ---------- 事件 ----------

    def _on_sender_edited(self):
        """根据发件邮箱后缀自动填充常见 SMTP 服务器."""
        email = self.edt_sender.text().strip().lower()
        domain = email.split('@')[-1] if '@' in email else ''
        preset = SMTP_PRESETS.get(domain)
        if preset and not self.edt_smtp.text().strip():
            self.edt_smtp.setText(preset[0])
            self.spn_port.setValue(preset[1])

    def _on_toggle_pwd(self, checked: bool):
        self.edt_password.setEchoMode(QLineEdit.Normal if checked
                                      else QLineEdit.Password)

    def _on_test_connection(self):
        server = self.edt_smtp.text().strip()
        user = self.edt_sender.text().strip()
        password = self.edt_password.text()
        if not (server and user and password):
            QMessageBox.warning(self, '测试连接',
                                '请先填写发件邮箱、SMTP服务器和密码/授权码')
            return
        self.btn_test.setEnabled(False)
        self.btn_test.setText('测试中…')
        self._thread = SmtpTestThread(server, self.spn_port.value(),
                                      user, password, self)
        self._thread.finished_test.connect(self._on_test_finished)
        self._thread.start()

    def _on_test_finished(self, ok: bool, msg: str):
        self.btn_test.setEnabled(True)
        self.btn_test.setText('✅ 测试连接')
        if ok:
            QMessageBox.information(self, '测试连接', msg)
        else:
            QMessageBox.warning(self, '测试连接', msg)

    def _on_authorize(self):
        if not STKCLIENT_AVAILABLE:
            QMessageBox.warning(self, '依赖缺失', INSTALL_HINT)
            return
        dlg = AuthDialog(self, self.ctx.api_client)
        if dlg.exec_() == QDialog.Accepted:
            self.ctx.config.api.oauth_state_saved = True
            self.ctx.config.save()
            self._refresh_auth_ui()
            self._on_refresh_devices()

    def _refresh_auth_ui(self):
        client = self.ctx.api_client
        if client.authorized:
            names = [d.name for d in client.devices]
            suffix = ' - %s' % names[0] if names else ''
            self.lbl_auth_status.setText('✅ 已授权%s' % suffix)
            self.lbl_auth_status.setObjectName('statusOk')
            self.cmb_device.setEnabled(True)
            self.btn_refresh_devices.setEnabled(True)
        else:
            self.lbl_auth_status.setText('❌ 未授权')
            self.lbl_auth_status.setObjectName('statusErr')
            self.cmb_device.setEnabled(False)
            self.btn_refresh_devices.setEnabled(False)
        # 重新应用样式使 objectName 变化生效
        self.lbl_auth_status.style().unpolish(self.lbl_auth_status)
        self.lbl_auth_status.style().polish(self.lbl_auth_status)

    def _on_refresh_devices(self):
        if not self.ctx.api_client.authorized:
            return
        self.btn_refresh_devices.setEnabled(False)
        self._thread = LoadDevicesThread(self.ctx.api_client, self)
        self._thread.loaded.connect(self._on_devices_loaded)
        self._thread.failed.connect(self._on_devices_failed)
        self._thread.start()

    def _on_devices_loaded(self, devices: list):
        self.btn_refresh_devices.setEnabled(True)
        last_serial = self.ctx.config.api.last_device_serial
        self.cmb_device.clear()
        for d in devices:
            self.cmb_device.addItem(d.display(), d.serial)
        if last_serial:
            idx = self.cmb_device.findData(last_serial)
            if idx >= 0:
                self.cmb_device.setCurrentIndex(idx)
        self._refresh_auth_ui()

    def _on_devices_failed(self, error: str):
        self.btn_refresh_devices.setEnabled(True)
        QMessageBox.warning(self, '获取设备失败', error)

    def _on_save(self):
        cfg = self.ctx.config
        cfg.email.sender_email = self.edt_sender.text().strip()
        cfg.email.smtp_server = self.edt_smtp.text().strip()
        cfg.email.smtp_port = self.spn_port.value()
        cfg.email.password = self.edt_password.text()
        cfg.email.kindle_email = self.edt_kindle.text().strip()
        if self.cmb_device.currentData():
            cfg.api.last_device_serial = self.cmb_device.currentData()
        cfg.general.auto_delete_temp = self.chk_auto_delete.isChecked()
        cfg.general.size_warning = self.chk_size_warning.isChecked()
        cfg.general.remember_push_method = self.chk_remember.isChecked()
        cfg.general.size_warning_threshold = self.spn_threshold.value()
        cfg.general.log_keep_days = self.spn_keep_days.value()
        if cfg.save():
            logger.info('设置已保存')
            self.accept()
        else:
            QMessageBox.critical(self, '保存失败', '配置写入失败，请检查目录权限')

    def _on_reset(self):
        """恢复通用设置默认值（保存后生效）."""
        self.chk_auto_delete.setChecked(False)
        self.chk_size_warning.setChecked(True)
        self.chk_remember.setChecked(True)
        self.spn_threshold.setValue(50)
        self.spn_keep_days.setValue(30)

    def _on_export_config(self):
        self.ctx.config.save()
        src = self.ctx.config_path
        if not os.path.exists(src):
            QMessageBox.warning(self, '导出配置', '配置文件不存在')
            return
        path, _ = QFileDialog.getSaveFileName(
            self, '导出配置', 'kindle_push_config.json', 'JSON 文件 (*.json)')
        if not path:
            return
        try:
            shutil.copy2(src, path)
        except OSError as e:
            QMessageBox.critical(self, '导出失败', '配置导出失败: %s' % e)
            return
        QMessageBox.information(self, '导出成功',
                                '配置已导出到：\n%s\n（密码为加密存储，可放心分享排障）' % path)
