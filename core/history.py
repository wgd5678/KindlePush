# -*- coding: utf-8 -*-
"""推送历史记录（SRS 3.7）：JSON 落盘，主窗口展示最近 5 条."""
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, fields

from utils.helpers import now_display

logger = logging.getLogger('kindle_push.history')

MAX_RECORDS = 500


@dataclass
class HistoryRecord:
    time: str
    file_name: str
    method_label: str
    status_label: str
    detail: str = ''
    duration_secs: float = 0.0
    file_size: int = 0

    def display(self) -> str:
        from utils.helpers import format_duration
        text = '%s  %-24s  %s  %s  耗时 %s' % (
            self.time, self.file_name[:24], self.status_label,
            self.method_label, format_duration(self.duration_secs))
        if self.detail:
            text += '  (%s)' % self.detail
        return text

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'HistoryRecord':
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


class HistoryStore:
    """推送历史持久化存储."""

    def __init__(self, path: str, max_records: int = MAX_RECORDS):
        self.path = path
        self.max_records = max_records
        self.records = []
        self.load()

    def load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            self.records = [HistoryRecord.from_dict(item)
                            for item in raw if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError, TypeError) as e:
            logger.warning('历史记录读取失败: %s', e)
            self.records = []

    def add(self, record: HistoryRecord):
        self.records.append(record)
        if len(self.records) > self.max_records:
            self.records = self.records[-self.max_records:]
        self._save()

    def recent(self, n: int = 5) -> list:
        return list(reversed(self.records[-n:]))

    def _save(self):
        dir_name = os.path.dirname(self.path) or '.'
        try:
            fd, tmp_path = tempfile.mkstemp(prefix='.history_', suffix='.tmp',
                                            dir=dir_name)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump([r.to_dict() for r in self.records],
                          f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.path)
        except OSError as e:
            logger.error('历史记录保存失败: %s', e)


def make_record(file_name: str, method_label: str, status_label: str,
                detail: str, duration_secs: float, file_size: int) -> HistoryRecord:
    return HistoryRecord(
        time=now_display('%Y-%m-%d %H:%M'),
        file_name=file_name,
        method_label=method_label,
        status_label=status_label,
        detail=detail,
        duration_secs=round(duration_secs, 1),
        file_size=file_size,
    )
