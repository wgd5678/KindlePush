# -*- coding: utf-8 -*-
"""推送引擎（SRS 3.4）：后台线程调度三种推送方式，逐文件更新状态."""
import logging
import os
import time

from PyQt5.QtCore import QThread, pyqtSignal

from core.api_client import ApiPushError
from core.converter import (ConvertError, convert_azw3_to_epub,
                            convert_pdf_to_epub, is_kindle_book_file)
from core.email_sender import EmailPushError, send_by_email
from core.history import make_record
from core.usb_pusher import UsbPushError, push_by_usb
from models.file_task import (METHOD_API, METHOD_EMAIL, METHOD_LABELS,
                              METHOD_USB, STATUS_FAILED, STATUS_LABELS,
                              STATUS_PENDING, STATUS_PUSHING, STATUS_SUCCESS)
from utils.helpers import now_display

logger = logging.getLogger('kindle_push.engine')


class PushWorker(QThread):
    """推送工作线程：依次推送任务列表，逐文件汇报状态与进度."""

    task_started = pyqtSignal(str)                 # task_id
    task_progress = pyqtSignal(str, int)           # task_id, percent
    task_finished = pyqtSignal(str, str, str)      # task_id, status, error_msg
    all_finished = pyqtSignal(int, int)            # success_count, failed_count

    def __init__(self, tasks, method: str, config, history,
                 api_client=None, device: str = '', convert: bool = True,
                 parent=None):
        super().__init__(parent)
        self.tasks = list(tasks)
        self.method = method
        self.config = config
        self.history = history
        self.api_client = api_client
        self.device = device
        self.convert = convert
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        success = failed = 0
        for task in self.tasks:
            if self._abort:
                logger.info('推送任务被中止')
                break
            if task.status not in (STATUS_PENDING,):
                continue
            self.task_started.emit(task.id)
            task.status = STATUS_PUSHING
            task.push_method = self.method
            task.error_msg = ''
            started = time.time()
            error = ''
            note = ''
            try:
                note = self._push_one(task) or ''
                task.status = STATUS_SUCCESS
                success += 1
            except (EmailPushError, ApiPushError, UsbPushError, ConvertError) as e:
                error = str(e)
                task.status = STATUS_FAILED
                failed += 1
            except Exception as e:  # 兜底，避免线程静默崩溃
                logger.exception('推送异常: %s', task.file_name)
                error = '推送异常: %s' % e
                task.status = STATUS_FAILED
                failed += 1
            task.completed_at = now_display()
            task.error_msg = error
            duration = time.time() - started
            if error:
                logger.error('推送失败: %s → %s', task.file_name, error)
            if self.method == METHOD_EMAIL:
                method_label = '邮件推送·转换' if self.convert else '邮件推送·原样'
            else:
                method_label = METHOD_LABELS.get(self.method, self.method)
            self.history.add(make_record(
                file_name=task.file_name,
                method_label=method_label,
                status_label=STATUS_LABELS.get(task.status, task.status),
                detail=(error or note),
                duration_secs=duration,
                file_size=task.file_size,
            ))
            self.task_finished.emit(task.id, task.status, error)
        self.all_finished.emit(success, failed)

    # ---------- 分方式推送 ----------

    def _push_one(self, task):
        """执行单文件推送.

        :return: 附注文本（如 '已本地转换为EPUB'），无附注返回 ''
        """
        if self.method == METHOD_EMAIL:
            self._push_email(task)
        elif self.method == METHOD_API:
            return self._push_api(task)
        elif self.method == METHOD_USB:
            self._push_usb(task)
        else:
            raise ValueError('未知推送方式: %s' % self.method)
        return ''

    def _push_email(self, task):
        # 亚马逊 2022 年底起停止接受 MOBI 系格式，邮件通道直接给出明确提示
        if is_kindle_book_file(task.file_path):
            raise EmailPushError('邮件通道不支持 azw3/azw/mobi/prc'
                                 '（亚马逊已停止接受），请改用 API 推送或 USB')
        # 文件大小拦截（SRS 5.2）：超限直接建议改用 API
        general = self.config.general
        limit_mb = general.size_warning_threshold
        if general.size_warning and limit_mb > 0 \
                and task.file_size > limit_mb * 1024 * 1024:
            raise EmailPushError('文件超过%dMB，请使用API推送方式' % limit_mb)
        email_cfg = self.config.email
        if not email_cfg.is_complete():
            raise EmailPushError('邮件配置不完整（缺少：%s）'
                                 % '、'.join(email_cfg.missing_items()))
        self.task_progress.emit(task.id, 15)
        send_by_email(
            file_path=task.file_path,
            kindle_email=email_cfg.kindle_email,
            sender_email=email_cfg.sender_email,
            smtp_config={
                'server': email_cfg.smtp_server,
                'port': email_cfg.smtp_port,
                'password': email_cfg.password,
            },
            convert=self.convert,
        )
        self.task_progress.emit(task.id, 100)

    def _push_api(self, task):
        if self.api_client is None:
            raise ApiPushError('API 客户端未初始化')
        if not self.api_client.authorized:
            raise ApiPushError('授权已过期，请重新授权')
        title = os.path.splitext(task.file_name)[0] or task.file_name
        file_path = task.file_path
        converted = False

        if is_kindle_book_file(file_path):
            # AZW3/AZW/MOBI/PRC：亚马逊已停止接收，无线推送唯一途径是
            # 本地转 EPUB（与"转换"选项无关，强制执行）。
            # 转换失败（如带 DRM）无法回退原文件（亚马逊同样拒收），直接报错。
            def kindle_conv_cb(p):
                self.task_progress.emit(task.id, min(60, int(p * 0.6)))

            file_path = convert_azw3_to_epub(file_path,
                                             progress_cb=kindle_conv_cb)
            converted = True
        elif self.convert and task.file_format.upper() == 'PDF':
            # 转换模式（仅 PDF）：本地转 EPUB 后推送，无需邮箱。
            # 转换失败时回退为推送原文件，不让整次推送失败。
            try:
                def conv_cb(p):
                    self.task_progress.emit(task.id, min(60, int(p * 0.6)))

                file_path = convert_pdf_to_epub(task.file_path,
                                                progress_cb=conv_cb)
                converted = True
            except ConvertError as e:
                logger.warning('本地转换失败，改推原文件: %s → %s',
                               task.file_name, e)
                self.task_progress.emit(task.id, 5)

        def cb(percent):
            if converted:
                self.task_progress.emit(task.id, 60 + int(percent * 0.4))
            else:
                self.task_progress.emit(task.id, percent)

        self.api_client.send_file_with_progress(
            file_path, self.device, progress_cb=cb, title=title)

        if converted and self.config.general.auto_delete_temp:
            try:
                os.remove(file_path)
            except OSError:
                pass
        return '已本地转换为EPUB' if converted else ''

    def _push_usb(self, task):
        def cb(percent):
            self.task_progress.emit(task.id, percent)

        push_by_usb(task.file_path, self.device, progress_cb=cb)
