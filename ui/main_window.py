# -*- coding: utf-8 -*-
"""主窗口（SRS 4.1）：文件管理、推送方式选择、进度展示、推送历史."""
import logging
import os
import shutil

from PyQt5.QtCore import QPoint, Qt, pyqtSlot
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox,
                             QComboBox, QDialog, QFileDialog, QGroupBox,
                             QHBoxLayout, QHeaderView, QLabel, QListWidget,
                             QMainWindow, QMenu, QMessageBox, QProgressBar,
                             QPushButton, QRadioButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from core.converter import OCR_AVAILABLE
from core.push_engine import PushWorker
from core.usb_pusher import detect_kindle_drives
from models.file_task import (METHOD_API, METHOD_EMAIL, METHOD_LABELS,
                              METHOD_USB, STATUS_FAILED, STATUS_LABELS,
                              STATUS_PENDING, STATUS_SUCCESS)
from ui.auth_dialog import AuthDialog
from ui.common import LoadDevicesThread
from ui.log_dialog import LogDialog
from ui.settings_dialog import SettingsDialog
from utils.helpers import format_size, get_app_file, pdf_has_text_layer

logger = logging.getLogger('kindle_push.ui.main')

COL_CHECK, COL_NAME, COL_SIZE, COL_FORMAT, COL_STATUS, COL_METHOD, COL_ACTION = range(7)
METHODS = [
    (METHOD_EMAIL, '● 邮件推送'),
    (METHOD_API, '● API推送'),
    (METHOD_USB, '● USB传输'),
]


class MainWindow(QMainWindow):
    """Kindle 推送助手主窗口."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.worker = None
        self._thread = None
        self._updating = False
        self.setWindowTitle('Kindle 推送助手')
        self.setWindowIcon(QIcon(get_app_file('resources/icon.ico')))
        self.setMinimumSize(900, 660)
        self.resize(980, 720)
        self.setAcceptDrops(True)
        self._build_ui()
        self._connect_signals()
        self._restore_method()
        self.refresh_table()
        self._refresh_history_view()
        self._on_method_changed()

    # ==================== UI 构建 ====================

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 8)
        root.setSpacing(10)

        # ---- 工具栏 ----
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.btn_add = QPushButton('📎 添加文件')
        self.btn_remove = QPushButton('🗑️ 删除')
        self.btn_clear = QPushButton('📋 清空列表')
        toolbar.addWidget(self.btn_add)
        toolbar.addWidget(self.btn_remove)
        toolbar.addWidget(self.btn_clear)
        toolbar.addStretch(1)
        self.lbl_stats = QLabel('共: 0个  总大小: 0B')
        self.lbl_stats.setObjectName('hintLabel')
        toolbar.addWidget(self.lbl_stats)
        root.addLayout(toolbar)

        # ---- 文件列表 ----
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ['', '文件名', '大小', '格式', '状态', '推送方式', '操作'])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        for col in (COL_CHECK, COL_SIZE, COL_FORMAT, COL_STATUS,
                    COL_METHOD, COL_ACTION):
            header.setSectionResizeMode(col, QHeaderView.Fixed)
        self.table.setColumnWidth(COL_CHECK, 30)
        self.table.setColumnWidth(COL_SIZE, 86)
        self.table.setColumnWidth(COL_FORMAT, 64)
        self.table.setColumnWidth(COL_STATUS, 96)
        self.table.setColumnWidth(COL_METHOD, 90)
        self.table.setColumnWidth(COL_ACTION, 70)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(200)
        root.addWidget(self.table, 1)

        # ---- 推送选项 ----
        box = QGroupBox('推送选项')
        box_layout = QVBoxLayout(box)

        method_row = QHBoxLayout()
        method_row.addWidget(QLabel('推送方式:'))
        self.method_group = QButtonGroup(self)
        for i, (method, text) in enumerate(METHODS):
            radio = QRadioButton(text)
            radio.setProperty('method', method)
            self.method_group.addButton(radio, i)
            method_row.addWidget(radio)
            if i == 0:
                radio.setChecked(True)
        method_row.addStretch(1)
        box_layout.addLayout(method_row)

        convert_row = QHBoxLayout()
        self.chk_convert = QCheckBox('转换为 Kindle 阅读格式（PDF 本地转 EPUB 后推送）')
        self.chk_convert.setChecked(self.ctx.config.general.convert_push)
        self.chk_convert.setToolTip(
            '勾选（默认）：\n'
            '· API 推送 —— PDF 先在本地转换成 EPUB（文字版直接提取；扫描版自动 OCR '
            '识别，耗时较长），再经 API 推送。亚马逊云端会把 EPUB 自动转成可重排的 '
            'Kindle 格式（可调字体、适应屏幕），全程无需配置邮箱。\n'
            '· azw3/azw/mobi 格式 —— 走 API 推送时始终会自动转换成 EPUB'
            '（亚马逊已停止接受这类格式），不受本选项影响。\n'
            '· 邮件推送 —— 邮件主题为 Convert，使用亚马逊云端转换（需配置邮箱；'
            '不支持 azw3/mobi）。\n'
            '取消勾选：原样推送，PDF 保持原始版式。USB 传输不做转换'
            '（azw3/mobi 为 Kindle 原生格式，USB 原样拷贝即可阅读）。')
        convert_row.addWidget(self.chk_convert)
        convert_row.addStretch(1)
        box_layout.addLayout(convert_row)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel('目标设备:'))
        self.cmb_target = QComboBox()
        target_row.addWidget(self.cmb_target, 1)
        self.btn_refresh_target = QPushButton('🔄 刷新')
        self.btn_refresh_target.setObjectName('miniBtn')
        target_row.addWidget(self.btn_refresh_target)
        self.lbl_target_info = QLabel('')
        self.lbl_target_info.setObjectName('hintLabel')
        target_row.addWidget(self.lbl_target_info)
        box_layout.addLayout(target_row)

        action_row = QHBoxLayout()
        self.btn_push = QPushButton('🚀 开始推送')
        self.btn_push.setObjectName('primaryBtn')
        self.btn_download = QPushButton('💾 下载选中文件')
        self.btn_log = QPushButton('📊 查看日志')
        self.btn_settings = QPushButton('⚙️ 设置')
        action_row.addWidget(self.btn_push)
        action_row.addWidget(self.btn_download)
        action_row.addStretch(1)
        action_row.addWidget(self.btn_log)
        action_row.addWidget(self.btn_settings)
        box_layout.addLayout(action_row)
        root.addWidget(box)

        # ---- 进度 ----
        progress_row = QHBoxLayout()
        progress_row.addWidget(QLabel('进度:'))
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        progress_row.addWidget(self.progress, 1)
        self.lbl_progress = QLabel('就绪')
        self.lbl_progress.setMinimumWidth(220)
        progress_row.addWidget(self.lbl_progress)
        root.addLayout(progress_row)

        # ---- 推送历史 ----
        history_box = QGroupBox('推送历史（最近 5 条）')
        history_layout = QVBoxLayout(history_box)
        self.history_list = QListWidget()
        self.history_list.setMinimumHeight(110)
        self.history_list.setMaximumHeight(150)
        history_layout.addWidget(self.history_list)
        root.addWidget(history_box)

        self.statusBar().showMessage('支持将文件直接拖拽到窗口添加')

    def _connect_signals(self):
        self.btn_add.clicked.connect(self._on_add_files)
        self.btn_remove.clicked.connect(self._on_remove_selected)
        self.btn_clear.clicked.connect(self._on_clear_list)
        self.btn_push.clicked.connect(self._on_start_push)
        self.btn_download.clicked.connect(self._on_download_selected)
        self.btn_log.clicked.connect(self._on_show_log)
        self.btn_settings.clicked.connect(self._on_show_settings)
        self.btn_refresh_target.clicked.connect(self._refresh_target_devices)
        self.method_group.buttonClicked.connect(self._on_method_changed)
        self.chk_convert.toggled.connect(self._on_convert_toggled)
        self.table.customContextMenuRequested.connect(self._on_table_menu)
        self.table.itemChanged.connect(self._on_item_changed)

    # ==================== 文件列表 ====================

    def refresh_table(self):
        self._updating = True
        self.table.setRowCount(0)
        for task in self.ctx.file_manager.tasks:
            self._append_row(task)
        self._updating = False
        self._update_stats()

    def _append_row(self, task):
        row = self.table.rowCount()
        self.table.insertRow(row)

        check = QTableWidgetItem()
        check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        check.setCheckState(Qt.Unchecked)
        check.setData(Qt.UserRole, task.id)
        self.table.setItem(row, COL_CHECK, check)

        name = QTableWidgetItem(task.file_name)
        name.setData(Qt.UserRole, task.id)
        name.setToolTip(task.file_path)
        self.table.setItem(row, COL_NAME, name)

        self.table.setItem(row, COL_SIZE, QTableWidgetItem(format_size(task.file_size)))
        self.table.setItem(row, COL_FORMAT, QTableWidgetItem(task.file_format))

        status = QTableWidgetItem(STATUS_LABELS.get(task.status, task.status))
        status.setData(Qt.UserRole, task.id)
        if task.error_msg:
            status.setToolTip(task.error_msg)
        self.table.setItem(row, COL_STATUS, status)

        self.table.setItem(row, COL_METHOD,
                           QTableWidgetItem(METHOD_LABELS.get(task.push_method, '-')))

        btn = QPushButton('下载')
        btn.setObjectName('miniBtn')
        btn.clicked.connect(lambda _checked=False, t=task: self._download_tasks([t]))
        self.table.setCellWidget(row, COL_ACTION, btn)

    def _row_of(self, task_id: str) -> int:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, COL_CHECK)
            if item and item.data(Qt.UserRole) == task_id:
                return row
        return -1

    def _update_row(self, task):
        row = self._row_of(task.id)
        if row < 0:
            return
        status_item = self.table.item(row, COL_STATUS)
        status_item.setText(STATUS_LABELS.get(task.status, task.status))
        status_item.setToolTip(task.error_msg or '')
        self.table.item(row, COL_METHOD).setText(
            METHOD_LABELS.get(task.push_method, '-'))

    def _update_stats(self):
        count, total = self.ctx.file_manager.stats()
        self.lbl_stats.setText('共: %d个  总大小: %s' % (count, format_size(total)))

    def _checked_tasks(self):
        tasks = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, COL_CHECK)
            if item and item.checkState() == Qt.Checked:
                task = self.ctx.file_manager.get_task(item.data(Qt.UserRole))
                if task:
                    tasks.append(task)
        return tasks

    @pyqtSlot(QTableWidgetItem)
    def _on_item_changed(self, item: QTableWidgetItem):
        if self._updating or item.column() != COL_CHECK:
            return
        self._update_stats()

    def _on_add_files(self):
        from utils.helpers import SUPPORTED_EXTENSIONS
        filter_str = '支持的文档 (%s);;所有文件 (*.*)' % ' '.join(
            '*' + ext for ext in SUPPORTED_EXTENSIONS)
        paths, _ = QFileDialog.getOpenFileNames(self, '添加文件', '', filter_str)
        if paths:
            self._add_paths(paths)

    def _add_paths(self, paths):
        added, skipped = self.ctx.file_manager.add_files(paths)
        self.refresh_table()
        if skipped:
            QMessageBox.information(self, '部分文件未添加', '\n'.join(skipped))

    def _on_remove_selected(self):
        ids = [t.id for t in self._checked_tasks()]
        if not ids:
            ids = []
            for row in sorted({i.row() for i in self.table.selectedItems()},
                              reverse=True):
                item = self.table.item(row, COL_CHECK)
                if item:
                    ids.append(item.data(Qt.UserRole))
        if not ids:
            QMessageBox.information(self, '提示', '请先勾选或选中要删除的文件')
            return
        self.ctx.file_manager.remove_tasks(ids)
        self.refresh_table()

    def _on_clear_list(self):
        if self.ctx.file_manager.clear_pending():
            self.refresh_table()

    def _on_table_menu(self, pos: QPoint):
        item = self.table.itemAt(pos)
        if item is None:
            return
        row = item.row()
        task_id = self.table.item(row, COL_CHECK).data(Qt.UserRole)
        task = self.ctx.file_manager.get_task(task_id)
        if task is None:
            return
        menu = QMenu(self)
        act_save = menu.addAction('💾 另存为…')
        act_remove = menu.addAction('🗑️ 从列表移除')
        chosen = menu.exec_(self.table.viewport().mapToGlobal(pos))
        if chosen == act_save:
            self._download_tasks([task])
        elif chosen == act_remove:
            self.ctx.file_manager.remove_tasks([task.id])
            self.refresh_table()

    # ==================== 推送方式与目标 ====================

    def current_method(self) -> str:
        btn = self.method_group.checkedButton()
        return btn.property('method') if btn else METHOD_EMAIL

    def _restore_method(self):
        g = self.ctx.config.general
        if g.remember_push_method:
            for radio in self.method_group.buttons():
                if radio.property('method') == g.last_push_method:
                    radio.setChecked(True)
                    break

    def _on_convert_toggled(self, checked: bool):
        self.ctx.config.general.convert_push = checked
        self.ctx.config.save()
        if checked and self.current_method() == METHOD_API:
            self.statusBar().showMessage(
                '已勾选转换：API 推送时 PDF 将先在本地转换为 EPUB（无需邮箱）', 6000)

    def _on_method_changed(self):
        method = self.current_method()
        if method == METHOD_EMAIL:
            self.cmb_target.setVisible(False)
            self.btn_refresh_target.setVisible(False)
            email = self.ctx.config.email.kindle_email
            self.lbl_target_info.setText(
                'Kindle邮箱: %s' % email if email else '未配置，请先打开「设置」填写邮箱')
        else:
            self.cmb_target.setVisible(True)
            self.btn_refresh_target.setVisible(True)
            self.lbl_target_info.setText('')
            self._refresh_target_devices()

    def _refresh_target_devices(self):
        method = self.current_method()
        if method == METHOD_EMAIL:
            return
        if method == METHOD_API:
            client = self.ctx.api_client
            if not client.authorized:
                self.cmb_target.clear()
                self.lbl_target_info.setText('未授权，点击「开始推送」时将引导授权')
                return
            self.lbl_target_info.setText('正在获取设备列表…')
            self.btn_refresh_target.setEnabled(False)
            self._thread = LoadDevicesThread(client, self)
            self._thread.loaded.connect(self._on_devices_loaded)
            self._thread.failed.connect(self._on_devices_failed)
            self._thread.start()
        elif method == METHOD_USB:
            self.cmb_target.clear()
            drives = detect_kindle_drives()
            for drive, label, confirmed in drives:
                mark = '' if confirmed else '（疑似）'
                self.cmb_target.addItem('%s %s%s' % (drive, label, mark), drive)
            if not drives:
                self.lbl_target_info.setText('未检测到Kindle设备，请通过USB连接后点「刷新」')
            else:
                self.lbl_target_info.setText('')

    def _on_devices_loaded(self, devices: list):
        self.btn_refresh_target.setEnabled(True)
        last_serial = self.ctx.config.api.last_device_serial
        self.cmb_target.clear()
        for d in devices:
            self.cmb_target.addItem(d.display(), d.serial)
        if last_serial:
            idx = self.cmb_target.findData(last_serial)
            if idx >= 0:
                self.cmb_target.setCurrentIndex(idx)
        self.lbl_target_info.setText('' if devices else '该账号下没有设备')

    def _on_devices_failed(self, error: str):
        self.btn_refresh_target.setEnabled(True)
        self.lbl_target_info.setText('设备列表获取失败: %s' % error)

    # ==================== 推送流程 ====================

    def _on_start_push(self):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, '提示', '推送正在进行中，请稍候')
            return
        method = self.current_method()
        convert = self.chk_convert.isChecked()

        if convert and method == METHOD_API:
            self.statusBar().showMessage(
                '转换已开启：PDF 将在本地转换为 EPUB 后经 API 推送（无需邮箱）', 6000)

        # 选取任务：优先勾选项；未勾选则推送所有待处理文件
        tasks = self._checked_tasks()
        if not tasks:
            tasks = [t for t in self.ctx.file_manager.tasks
                     if t.status == STATUS_PENDING]
        if not tasks:
            QMessageBox.information(self, '提示', '没有可推送的文件，请先添加文件')
            return

        device = ''
        if method == METHOD_EMAIL:
            email_cfg = self.ctx.config.email
            if not email_cfg.is_complete():
                QMessageBox.warning(
                    self, '配置不完整',
                    '请先在设置中完成邮件推送配置（缺少：%s）'
                    % '、'.join(email_cfg.missing_items()))
                self._on_show_settings()
                return
            # 超限拦截（SRS 5.2）
            general = self.ctx.config.general
            if general.size_warning and general.size_warning_threshold > 0:
                limit = general.size_warning_threshold * 1024 * 1024
                too_big = [t.file_name for t in tasks if t.file_size > limit]
                if too_big and len(too_big) == len(tasks):
                    QMessageBox.warning(
                        self, '文件过大',
                        '以下文件超过%dMB，无法邮件推送，请改用 API 推送：\n%s'
                        % (general.size_warning_threshold, '\n'.join(too_big)))
                    return
                if too_big:
                    QMessageBox.warning(
                        self, '部分文件过大',
                        '以下文件超过%dMB，本次跳过（建议改用 API 推送）：\n%s'
                        % (general.size_warning_threshold, '\n'.join(too_big)))
                    tasks = [t for t in tasks if t.file_size <= limit]
        elif method == METHOD_API:
            if not self._ensure_api_authorized():
                return
            device = self.cmb_target.currentData()
            if not device:
                QMessageBox.warning(self, '未选择设备', '请先选择目标 Kindle 设备')
                return
        else:  # USB
            device = self.cmb_target.currentData()
            if not device:
                QMessageBox.warning(self, '未检测到设备',
                                    '未检测到Kindle设备，请通过USB连接后点「刷新」')
                return

        # 扫描版 PDF 提示：不同通道对扫描版的处理方式不同
        if convert:
            scanned = [t.file_name for t in tasks
                       if t.file_format.upper() == 'PDF'
                       and not pdf_has_text_layer(t.file_path)]
            if scanned and method == METHOD_API:
                if OCR_AVAILABLE:
                    QMessageBox.information(
                        self, '扫描版 PDF',
                        '以下 PDF 为扫描版（无文字层），本地转换时将逐页进行 OCR '
                        '识别，耗时较长（约每页 1~3 秒），请耐心等待：\n%s'
                        % '\n'.join(scanned))
                else:
                    QMessageBox.warning(
                        self, '扫描版 PDF',
                        '以下 PDF 为扫描版（无文字层），且本机未检测到 OCR 组件，'
                        '无法本地转换，将按原样推送：\n%s\n\n'
                        '如需转换，可改用「邮件推送」（亚马逊云端转换）'
                        '或安装 rapidocr-onnxruntime 后重试。'
                        % '\n'.join(scanned))
            elif scanned and method == METHOD_EMAIL:
                QMessageBox.warning(
                    self, '疑似扫描版 PDF',
                    '以下 PDF 未检测到文字层（疑似扫描版）：\n%s\n\n'
                    '亚马逊云端转换依赖文字层，扫描版转换后阅读体验可能提升有限。'
                    '将继续推送，如不需要转换请取消勾选「转换为 Kindle 阅读格式」。'
                    % '\n'.join(scanned))

        # 重置任务状态
        for t in tasks:
            t.status = STATUS_PENDING
            t.error_msg = ''
            self._update_row(t)
        self.refresh_table()

        # 记录推送方式并启动
        if self.ctx.config.general.remember_push_method:
            self.ctx.config.general.last_push_method = method
            self.ctx.config.save()

        self._set_pushing_ui(True)
        self.progress.setValue(0)
        self.lbl_progress.setText('准备推送 %d 个文件…' % len(tasks))
        self.worker = PushWorker(tasks, method, self.ctx.config,
                                 self.ctx.history,
                                 api_client=self.ctx.api_client,
                                 device=device, convert=convert, parent=self)
        self.worker.task_started.connect(self._on_task_started)
        self.worker.task_progress.connect(self._on_task_progress)
        self.worker.task_finished.connect(self._on_task_finished)
        self.worker.all_finished.connect(self._on_all_finished)
        self.worker.start()

    def _ensure_api_authorized(self) -> bool:
        if self.ctx.api_client.authorized:
            return True
        dlg = AuthDialog(self, self.ctx.api_client)
        if dlg.exec_() == QDialog.Accepted:
            self.ctx.config.api.oauth_state_saved = True
            self.ctx.config.save()
            self._on_method_changed()
            return True
        return False

    def _set_pushing_ui(self, pushing: bool):
        self.btn_push.setEnabled(not pushing)
        self.btn_push.setText('⏳ 推送中…' if pushing else '🚀 开始推送')
        self.btn_settings.setEnabled(not pushing)

    @pyqtSlot(str)
    def _on_task_started(self, task_id: str):
        task = self.ctx.file_manager.get_task(task_id)
        if task:
            self.lbl_progress.setText('正在推送: %s' % task.file_name)
        self.progress.setValue(0)

    @pyqtSlot(str, int)
    def _on_task_progress(self, task_id: str, percent: int):
        self.progress.setValue(percent)

    @pyqtSlot(str, str, str)
    def _on_task_finished(self, task_id: str, status: str, error: str):
        task = self.ctx.file_manager.get_task(task_id)
        if task:
            self._update_row(task)
            if error:
                logger.warning('文件推送失败: %s → %s', task.file_name, error)

    @pyqtSlot(int, int)
    def _on_all_finished(self, success: int, failed: int):
        self._set_pushing_ui(False)
        self.progress.setValue(100 if failed == 0 else self.progress.value())
        summary = '推送完成：成功 %d 个，失败 %d 个' % (success, failed)
        self.lbl_progress.setText(summary)
        self.statusBar().showMessage(summary, 8000)
        logger.info(summary)
        self._refresh_history_view()
        if failed:
            QMessageBox.warning(self, '推送完成', summary + '\n详情见推送历史与日志')
        elif success:
            QMessageBox.information(self, '推送完成', summary)

    # ==================== 本地下载（SRS 3.5） ====================

    def _on_download_selected(self):
        tasks = self._checked_tasks()
        if not tasks:
            QMessageBox.information(self, '提示', '请先勾选要下载的文件')
            return
        self._download_tasks(tasks)

    def _download_tasks(self, tasks):
        tasks = [t for t in tasks if t]
        if not tasks:
            return
        missing = [t.file_name for t in tasks if not os.path.exists(t.file_path)]
        if missing:
            QMessageBox.warning(self, '文件不存在',
                                '以下源文件已不存在：\n%s' % '\n'.join(missing))
        valid = [t for t in tasks if os.path.exists(t.file_path)]
        if not valid:
            return
        dest_dir = QFileDialog.getExistingDirectory(self, '选择保存目录')
        if not dest_dir:
            return
        copied = 0
        for t in valid:
            try:
                shutil.copy2(t.file_path, os.path.join(dest_dir, t.file_name))
                copied += 1
            except OSError as e:
                QMessageBox.warning(self, '下载失败',
                                    '%s 复制失败: %s' % (t.file_name, e))
        if copied:
            logger.info('本地下载 %d 个文件到 %s', copied, dest_dir)
            self.statusBar().showMessage('已下载 %d 个文件到 %s' % (copied, dest_dir), 8000)

    # ==================== 历史 / 日志 / 设置 ====================

    def _refresh_history_view(self):
        self.history_list.clear()
        records = self.ctx.history.recent(5)
        if not records:
            self.history_list.addItem('（暂无推送记录）')
            return
        for r in records:
            self.history_list.addItem(r.display())

    def _on_show_log(self):
        dlg = LogDialog(self, self.ctx)
        dlg.exec_()

    def _on_show_settings(self):
        dlg = SettingsDialog(self, self.ctx)
        if dlg.exec_() == QDialog.Accepted:
            logger.info('设置已更新')
            self._on_method_changed()

    # ==================== 拖拽添加 ====================

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                paths.append(url.toLocalFile())
        if paths:
            self._add_paths(paths)

    # ==================== 关闭 ====================

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            ret = QMessageBox.question(
                self, '确认退出', '推送仍在进行中，确定要退出吗？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                event.ignore()
                return
            self.worker.abort()
            self.worker.wait(3000)
        event.accept()
