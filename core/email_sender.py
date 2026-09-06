# -*- coding: utf-8 -*-
"""邮件推送模块（SRS 3.4.1）.

邮件主题固定为 Convert，触发亚马逊云端自动转换（PDF/EPUB 等 → KFX）。
用户须先将发件邮箱加入亚马逊「已批准的个人文档邮件列表」。
"""
import logging
import os
import smtplib
import socket
import ssl
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger('kindle_push.email')

# 邮件主题：必须为 Convert 才能触发亚马逊自动转换（SRS 3.3.2）
CONVERT_SUBJECT = 'Convert'
MAX_RETRY = 3
RETRY_WAIT_SECS = 2
BODY_TEXT = ('This document is sent by Kindle Push Assistant '
             'and will be converted by Amazon automatically.')


class EmailPushError(Exception):
    """邮件推送失败."""


def build_message(file_path: str, kindle_email: str, sender_email: str,
                  convert: bool = True) -> MIMEMultipart:
    """构建带附件的邮件.

    :param convert: True 时主题为 Convert，触发亚马逊云端转换
        （PDF → 可重排的 Kindle 格式）；False 时主题为文件名，原样推送
    """
    if convert:
        subject = CONVERT_SUBJECT
    else:
        subject = os.path.splitext(os.path.basename(file_path))[0]
    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = kindle_email
    msg.attach(MIMEText(BODY_TEXT, 'plain', 'utf-8'))

    with open(file_path, 'rb') as f:
        data = f.read()
    name = os.path.basename(file_path)
    part = MIMEApplication(data)
    # RFC 2231 编码，兼容中文文件名
    part.add_header('Content-Disposition', 'attachment',
                    filename=('utf-8', '', name))
    msg.attach(part)
    return msg


def send_by_email(file_path: str, kindle_email: str, sender_email: str,
                  smtp_config: dict, convert: bool = True) -> bool:
    """通过邮件推送文件到 Kindle.

    :param file_path: 文件路径
    :param kindle_email: 目标 Kindle 邮箱
    :param sender_email: 发件邮箱
    :param smtp_config: {server, port, password}
    :param convert: True 时邮件主题为 Convert，亚马逊会将 PDF 转换为
        可重排格式；False 时原样推送（保持 PDF 版式）
    :return: 推送是否成功
    :raises EmailPushError: 推送失败（含中文用户提示）
    """
    server = smtp_config.get('server')
    try:
        port = int(smtp_config.get('port', 587))
    except (TypeError, ValueError):
        port = 587
    password = smtp_config.get('password', '')

    if not (server and port and password):
        raise EmailPushError('邮件配置不完整，请先在设置中填写邮箱配置')
    if not os.path.exists(file_path):
        raise EmailPushError('文件不存在: %s' % file_path)

    msg = build_message(file_path, kindle_email, sender_email, convert=convert)
    last_err = None

    for attempt in range(1, MAX_RETRY + 1):
        smtp = None
        try:
            context = ssl.create_default_context()
            if port == 465:
                smtp = smtplib.SMTP_SSL(server, port, timeout=30, context=context)
            else:
                smtp = smtplib.SMTP(server, port, timeout=30)
                smtp.starttls(context=context)
            smtp.login(sender_email, password)
            smtp.sendmail(sender_email, [kindle_email], msg.as_bytes())
            logger.info('邮件推送成功: %s → %s（%s:%s，第%d次尝试）',
                        os.path.basename(file_path), kindle_email,
                        server, port, attempt)
            return True
        except smtplib.SMTPAuthenticationError as e:
            logger.error('SMTP 认证失败: %s', e)
            raise EmailPushError('邮箱认证失败，请检查密码/授权码') from e
        except smtplib.SMTPRecipientsRefused as e:
            logger.error('收件人被拒绝: %s', e)
            raise EmailPushError('Kindle邮箱拒收，请确认发件邮箱已加入'
                                 '亚马逊「已批准的个人文档邮件列表」') from e
        except (smtplib.SMTPConnectError, socket.timeout,
                ConnectionError, OSError) as e:
            last_err = e
            logger.warning('SMTP 连接失败（第%d/%d次）: %s',
                           attempt, MAX_RETRY, e)
            if attempt < MAX_RETRY:
                time.sleep(RETRY_WAIT_SECS)
        except smtplib.SMTPException as e:
            logger.error('SMTP 发送异常: %s', e)
            raise EmailPushError('SMTP发送失败: %s' % e) from e
        finally:
            if smtp is not None:
                try:
                    smtp.quit()
                except Exception:
                    pass

    logger.error('SMTP 连接重试 %d 次均失败', MAX_RETRY)
    raise EmailPushError('邮件服务器连接失败，请检查网络和配置')
