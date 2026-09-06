# -*- coding: utf-8 -*-
"""文件管理模块（SRS 3.2）：添加、删除、清空与状态追踪."""
import logging
import os

from models.file_task import STATUS_PENDING, FileTask
from utils.helpers import SUPPORTED_EXTENSIONS

logger = logging.getLogger('kindle_push.file_manager')


class FileManager:
    """维护待推送文件任务列表."""

    def __init__(self):
        self.tasks = []

    def add_files(self, paths) -> tuple:
        """添加文件，返回 (新增任务列表, 跳过原因列表).

        自动过滤不支持的格式、不存在的文件与重复文件。
        """
        added, skipped = [], []
        existing = {t.file_path for t in self.tasks}
        for p in paths:
            p = os.path.normpath(p)
            name = os.path.basename(p)
            ext = os.path.splitext(p)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                skipped.append('%s（不支持的格式）' % name)
                continue
            if not os.path.isfile(p):
                skipped.append('%s（文件不存在）' % name)
                continue
            if p in existing:
                skipped.append('%s（已在列表中）' % name)
                continue
            task = FileTask(file_path=p)
            self.tasks.append(task)
            existing.add(p)
            added.append(task)
        if added:
            logger.info('添加 %d 个文件: %s', len(added),
                        ', '.join(t.file_name for t in added))
        if skipped:
            logger.warning('跳过 %d 个文件: %s', len(skipped), '; '.join(skipped))
        return added, skipped

    def get_task(self, task_id: str):
        for t in self.tasks:
            if t.id == task_id:
                return t
        return None

    def remove_tasks(self, task_ids) -> int:
        id_set = set(task_ids)
        before = len(self.tasks)
        self.tasks = [t for t in self.tasks if t.id not in id_set]
        removed = before - len(self.tasks)
        if removed:
            logger.info('从列表移除 %d 个文件', removed)
        return removed

    def clear_pending(self) -> int:
        """清空所有待处理文件（SRS 3.2.1 清空列表）."""
        before = len(self.tasks)
        self.tasks = [t for t in self.tasks if t.status != STATUS_PENDING]
        removed = before - len(self.tasks)
        if removed:
            logger.info('清空待处理文件 %d 个', removed)
        return removed

    def stats(self) -> tuple:
        """返回 (文件数, 总字节数)."""
        return len(self.tasks), sum(t.file_size for t in self.tasks)
