# -*- coding: utf-8 -*-
"""通用辅助函数."""
import os
import sys
from datetime import datetime

# 支持的文档格式（SRS 3.2.1）
# azw3/azw/mobi/prc 为 Kindle 原生格式：USB 原样拷贝；API 推送前自动转 EPUB；
# 邮件通道不支持（亚马逊已停止接受）
SUPPORTED_EXTENSIONS = ('.pdf', '.epub', '.doc', '.docx', '.txt', '.rtf',
                        '.azw3', '.azw', '.mobi', '.prc')

# 邮件推送附件大小上限（MB），亚马逊官方限制
EMAIL_SIZE_LIMIT_MB = 50


def get_app_dir() -> str:
    """应用数据目录：打包后为 exe 所在目录，开发时为项目根目录."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_app_file(rel_path: str) -> str:
    """解析随程序分发的资源文件路径（兼容 PyInstaller 打包）."""
    if getattr(sys, 'frozen', False):
        base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *rel_path.replace('\\', '/').split('/'))


def format_size(num_bytes) -> str:
    """字节数转人类可读格式."""
    try:
        size = float(num_bytes)
    except (TypeError, ValueError):
        return '0B'
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024 or unit == 'TB':
            if unit == 'B':
                return '%dB' % int(size)
            return '%.1f%s' % (size, unit)
        size /= 1024.0
    return '%.1fTB' % size


def format_duration(secs) -> str:
    """秒数转 "2m 12s" 形式."""
    try:
        secs = max(0, int(secs))
    except (TypeError, ValueError):
        return '0s'
    if secs < 60:
        return '%ds' % secs
    m, s = divmod(secs, 60)
    if m < 60:
        return '%dm %ds' % (m, s)
    h, m = divmod(m, 60)
    return '%dh %dm' % (h, m)


def now_display(fmt: str = '%Y-%m-%d %H:%M:%S') -> str:
    return datetime.now().strftime(fmt)


def pdf_has_text_layer(file_path: str) -> bool:
    """轻量启发式判断 PDF 是否含文字层（True=文字版, False=疑似扫描版）.

    读取文件头部若干 KB，查找 /Font 对象标记：文字版 PDF 必然嵌入字体
    引用，纯扫描图片版则没有。结果仅供提示，不影响推送流程。
    """
    try:
        with open(file_path, 'rb') as f:
            head = f.read(512 * 1024)
            if not head.startswith(b'%PDF'):
                return False
            if b'/Font' in head:
                return True
            # 大 PDF 的对象表可能在文件后部，再补读中段与尾部
            f.seek(0, os.SEEK_END)
            total = f.tell()
            if total > 512 * 1024:
                f.seek(max(0, total // 2 - 256 * 1024))
                mid = f.read(512 * 1024)
                if b'/Font' in mid:
                    return True
                f.seek(max(0, total - 256 * 1024))
                tail = f.read()
                if b'/Font' in tail:
                    return True
            return False
    except OSError:
        return False
