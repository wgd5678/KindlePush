# -*- coding: utf-8 -*-
"""日志系统（SRS 3.7）：按天滚动文件 + 控制台输出，自动清理过期日志."""
import glob
import logging
import os
from logging.handlers import TimedRotatingFileHandler

LOGGER_NAME = 'kindle_push'
LOG_BASE_NAME = 'kindle_push.log'

_FORMAT = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'


def setup_logger(log_dir: str, keep_days: int = 30) -> logging.Logger:
    """初始化日志：文件记录 DEBUG+，控制台 INFO+，保留 keep_days 天."""
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    log_file = os.path.join(log_dir, LOG_BASE_NAME)
    file_handler = TimedRotatingFileHandler(
        log_file, when='midnight', interval=1,
        backupCount=max(1, keep_days), encoding='utf-8')
    file_handler.suffix = '%Y-%m-%d.log'
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(console_handler)
    return logger


def get_logger(name: str = '') -> logging.Logger:
    if name:
        return logging.getLogger('%s.%s' % (LOGGER_NAME, name))
    return logging.getLogger(LOGGER_NAME)


def get_current_log_file(log_dir: str) -> str:
    return os.path.join(log_dir, LOG_BASE_NAME)


def export_logs(log_dir: str, dest_path: str) -> str:
    """导出全部日志（含滚动文件）到一个 TXT，便于问题反馈."""
    files = sorted(glob.glob(os.path.join(log_dir, LOG_BASE_NAME + '*')))
    chunks = []
    for fp in files:
        chunks.append('===== %s =====' % os.path.basename(fp))
        try:
            with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                chunks.append(f.read())
        except OSError as e:
            chunks.append('(读取失败: %s)' % e)
    with open(dest_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(chunks))
    return dest_path
