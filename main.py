# -*- coding: utf-8 -*-
"""Kindle 推送助手 - 程序入口."""
import sys
import traceback


def main():
    try:
        from app import run
        run()
    except Exception:
        # 启动失败兜底：尽量弹窗提示，否则打印到控制台
        try:
            from PyQt5.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, 'Kindle推送助手 启动失败',
                                 '程序启动失败：\n%s' % traceback.format_exc())
        except Exception:
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
