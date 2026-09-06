# -*- coding: utf-8 -*-
"""文件任务数据模型（SRS 3.2.2）."""
import os
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime

# 任务状态常量
STATUS_PENDING = 'pending'    # 待处理
STATUS_PUSHING = 'pushing'    # 推送中
STATUS_SUCCESS = 'success'    # 成功
STATUS_FAILED = 'failed'      # 失败

# 推送方式常量
METHOD_EMAIL = 'email'        # 邮件推送
METHOD_API = 'api'            # HTTP API 推送
METHOD_USB = 'usb'            # USB 传输

STATUS_LABELS = {
    STATUS_PENDING: '⏳ 待处理',
    STATUS_PUSHING: '⏳ 推送中',
    STATUS_SUCCESS: '✅ 成功',
    STATUS_FAILED: '❌ 失败',
}

METHOD_LABELS = {
    METHOD_EMAIL: '邮件推送',
    METHOD_API: 'API推送',
    METHOD_USB: 'USB传输',
    '': '-',
}


@dataclass
class FileTask:
    """文件推送任务."""

    file_path: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    file_name: str = ''
    file_size: int = 0
    file_format: str = ''
    status: str = STATUS_PENDING
    push_method: str = ''
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec='seconds'))
    completed_at: str = ''
    error_msg: str = ''

    def __post_init__(self):
        if not self.file_name:
            self.file_name = os.path.basename(self.file_path)
        if not self.file_format:
            self.file_format = os.path.splitext(self.file_name)[1].lstrip('.').upper()
        if not self.file_size:
            try:
                self.file_size = os.path.getsize(self.file_path)
            except OSError:
                self.file_size = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'FileTask':
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})
