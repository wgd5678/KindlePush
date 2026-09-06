# -*- coding: utf-8 -*-
"""Kindle 推送助手 - 主应用类（SRS 6 目录结构）.

负责初始化应用上下文（目录、日志、加密、配置、服务）并启动 GUI。
"""
import os
import sys

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QMessageBox

from core.api_client import KindleAPIClient
from core.file_manager import FileManager
from core.history import HistoryStore
from models.config import AppConfig
from utils.crypto import CryptoStore
from utils.helpers import get_app_dir, get_app_file
from utils.logger import setup_logger


class AppContext:
    """应用级上下文：路径、配置与各核心服务实例."""

    def __init__(self):
        self.app_dir = get_app_dir()
        self.log_dir = os.path.join(self.app_dir, 'logs')
        self.temp_dir = os.path.join(self.app_dir, 'temp')
        self.config_path = os.path.join(self.app_dir, 'config.json')
        self.history_path = os.path.join(self.app_dir, 'push_history.json')
        self.api_state_path = os.path.join(self.app_dir, 'api_oauth_state.json')
        self.key_path = os.path.join(self.app_dir, 'crypto.key')

        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)

        self.crypto = CryptoStore(self.key_path)
        self.config = AppConfig(self.config_path, self.crypto)
        self.config.load()

        self.logger = setup_logger(self.log_dir, self.config.general.log_keep_days)
        self.file_manager = FileManager()
        self.api_client = KindleAPIClient(self.api_state_path)
        self.api_client.load_state()
        self.history = HistoryStore(self.history_path)


def run():
    """程序主入口逻辑."""
    import traceback

    ctx = AppContext()
    app = QApplication(sys.argv)
    app.setApplicationName('Kindle推送助手')
    app.setOrganizationName('KindlePush')
    app.setWindowIcon(QIcon(get_app_file('resources/icon.ico')))

    # 全局样式
    qss_path = get_app_file('ui/styles.qss')
    if os.path.exists(qss_path):
        with open(qss_path, 'r', encoding='utf-8') as f:
            app.setStyleSheet(f.read())

    def excepthook(exc_type, exc_value, exc_tb):
        msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            ctx.logger.critical('未捕获异常:\n%s', msg)
        except Exception:
            pass
        QMessageBox.critical(None, '程序异常', '发生未处理的异常：\n%s' % msg)

    sys.excepthook = excepthook

    from ui.main_window import MainWindow
    window = MainWindow(ctx)
    window.show()
    ctx.logger.info('Kindle 推送助手启动（数据目录: %s）', ctx.app_dir)
    sys.exit(app.exec_())
