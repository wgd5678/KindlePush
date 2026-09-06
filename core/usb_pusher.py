# -*- coding: utf-8 -*-
"""USB 传输模块（SRS 3.4.3）：检测 Kindle 盘符并复制文件到 documents 目录."""
import ctypes
import logging
import os
import shutil
import sys

import psutil

logger = logging.getLogger('kindle_push.usb')

COPY_CHUNK = 1024 * 1024        # 1MB 分块，便于进度回调
SPACE_MARGIN = 10 * 1024 * 1024  # 额外预留 10MB 空间


class UsbPushError(Exception):
    """USB 传输失败."""


def _get_volume_label(drive: str) -> str:
    """读取盘符卷标（仅 Windows）."""
    if sys.platform != 'win32':
        return ''
    try:
        kernel32 = ctypes.windll.kernel32
        root = drive if drive.endswith('\\') else drive + '\\'
        buf = ctypes.create_unicode_buffer(261)
        fs_buf = ctypes.create_unicode_buffer(261)
        ok = kernel32.GetVolumeInformationW(
            root, buf, 261, None, None, None, fs_buf, 261)
        return buf.value if ok else ''
    except Exception:
        return ''


def detect_kindle_drives() -> list:
    """检测 Kindle 设备盘符.

    优先按卷标包含 "Kindle" 识别；其次识别带 documents 目录的可移动磁盘。
    :return: [(盘符路径, 卷标, 是否确认是Kindle)]
    """
    result = []
    for part in psutil.disk_partitions(all=False):
        mountpoint = part.mountpoint
        try:
            if not os.path.isdir(mountpoint):
                continue
        except OSError:
            continue
        removable = 'removable' in part.opts
        if not removable:
            continue
        label = _get_volume_label(mountpoint)
        has_documents = os.path.isdir(os.path.join(mountpoint, 'documents'))
        confirmed = 'kindle' in label.lower()
        if confirmed or has_documents:
            result.append((mountpoint, label or '未命名', confirmed))
            logger.info('检测到可移动设备: %s 卷标=%s Kindle确认=%s',
                        mountpoint, label, confirmed)
    return result


def push_by_usb(file_path: str, kindle_path: str, progress_cb=None) -> str:
    """通过 USB 推送文件：复制到 Kindle 盘 documents 目录.

    :param file_path: 源文件路径
    :param kindle_path: Kindle 盘符（如 E:\\）
    :param progress_cb: 进度回调 progress_cb(percent)
    :return: 目标文件完整路径
    """
    if not os.path.exists(file_path):
        raise UsbPushError('文件不存在: %s' % file_path)
    if not kindle_path or not os.path.isdir(kindle_path):
        raise UsbPushError('未检测到Kindle设备，请通过USB连接')

    dest_dir = os.path.join(kindle_path, 'documents')
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError as e:
        raise UsbPushError('无法创建 documents 目录: %s' % e) from e

    size = os.path.getsize(file_path)
    try:
        free = shutil.disk_usage(kindle_path).free
        if free < size + SPACE_MARGIN:
            raise UsbPushError('Kindle磁盘空间不足（剩余 %d MB，需要 %d MB）'
                               % (free // 1024 // 1024, size // 1024 // 1024 + 10))
    except OSError as e:
        raise UsbPushError('Kindle磁盘访问失败: %s' % e) from e

    dest = os.path.join(dest_dir, os.path.basename(file_path))
    tmp_dest = dest + '.tmp'
    copied = 0
    try:
        with open(file_path, 'rb') as src, open(tmp_dest, 'wb') as dst:
            while True:
                chunk = src.read(COPY_CHUNK)
                if not chunk:
                    break
                dst.write(chunk)
                copied += len(chunk)
                if progress_cb and size:
                    progress_cb(min(100, int(copied * 100 / size)))
        os.replace(tmp_dest, dest)
    except OSError as e:
        try:
            if os.path.exists(tmp_dest):
                os.remove(tmp_dest)
        except OSError:
            pass
        raise UsbPushError('文件复制失败: %s' % e) from e

    logger.info('USB 传输成功: %s → %s', os.path.basename(file_path), dest)
    return dest
