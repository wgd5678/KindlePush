# -*- coding: utf-8 -*-
"""日志查看与导出对话框（SRS 3.7）."""
import logging
import os

from PyQt5.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QMessageBox,
                             QPlainTextEdit, QPushButton, QVBoxLayout)

from utils.logger import export_logs, get_current_log_file

logger = logging.getLogger('kindle_push.ui.log')

MAX_PREVIEW_CHARS = 500 * 1024  # 预览上限 500KB，防止超大日志卡界面


class LogDialog(QDialog):
    """查看运行日志，支持导出为 TXT."""

    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle('运行日志')
        self.resize(760, 520)
        self._build_ui()
        self._load_log()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        layout.addWidget(self.txt_log)

        btn_row = QHBoxLayout()
        btn_refresh = QPushButton('🔄 刷新')
        btn_refresh.clicked.connect(self._load_log)
        btn_export = QPushButton('📄 导出日志')
        btn_export.clicked.connect(self._on_export)
        btn_close = QPushButton('关闭')
        btn_close.clicked.connect(self.accept)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_refresh)
        btn_row.addWidget(btn_export)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _load_log(self):
        log_file = get_current_log_file(self.ctx.log_dir)
        if not os.path.exists(log_file):
            self.txt_log.setPlainText('（暂无日志）')
            return
        try:
            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except OSError as e:
            self.txt_log.setPlainText('日志读取失败: %s' % e)
            return
        if len(content) > MAX_PREVIEW_CHARS:
            content = '…（日志过长，仅显示最后 %d 字符，完整内容请使用导出）…\n' % MAX_PREVIEW_CHARS \
                + content[-MAX_PREVIEW_CHARS:]
        self.txt_log.setPlainText(content)

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, '导出日志', 'kindle_push_logs.txt', '文本文件 (*.txt)')
        if not path:
            return
        try:
            export_logs(self.ctx.log_dir, path)
        except OSError as e:
            QMessageBox.critical(self, '导出失败', '日志导出失败: %s' % e)
            return
        logger.info('日志已导出: %s', path)
        QMessageBox.information(self, '导出成功', '日志已导出到：\n%s' % path)
