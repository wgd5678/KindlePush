# -*- coding: utf-8 -*-
"""API 推送模块（SRS 3.4.2）：封装 stkclient（pySendToKindle）SDK.

使用亚马逊官方 Send to Kindle 通道，OAuth2 授权，
突破邮件方式 50MB 附件限制，无需配置 SMTP。
"""
import logging
import os
from pathlib import Path

logger = logging.getLogger('kindle_push.api')

try:
    import stkclient
    STKCLIENT_AVAILABLE = True
except ImportError:  # 依赖缺失时给出明确指引而非崩溃
    stkclient = None
    STKCLIENT_AVAILABLE = False

INSTALL_HINT = '未检测到 stkclient 库，请先执行: pip install stkclient'


class ApiPushError(Exception):
    """API 推送失败."""


class DeviceInfo:
    """Kindle 设备信息."""

    def __init__(self, serial: str, name: str):
        self.serial = serial
        self.name = name or serial

    def display(self) -> str:
        return '%s (%s)' % (self.name, self.serial)

    def __repr__(self):
        return 'DeviceInfo(%r, %r)' % (self.serial, self.name)


class _ProgressFile:
    """包装文件对象，在读取（上传）时按已读字节回调进度百分比."""

    def __init__(self, fp, total: int, cb):
        self._fp = fp
        self._total = max(1, total)
        self._cb = cb
        self._read_bytes = 0

    def read(self, size=-1):
        data = self._fp.read(size)
        self._read_bytes += len(data)
        if self._cb:
            try:
                self._cb(min(100, int(self._read_bytes * 100 / self._total)))
            except Exception:
                pass
        return data

    def __getattr__(self, item):
        return getattr(self._fp, item)


class KindleAPIClient:
    """stkclient 封装：授权、设备列表、发送文件、状态持久化."""

    def __init__(self, state_path: str):
        self.state_path = state_path
        self.client = None
        self.devices = []
        self._oauth = None

    @property
    def authorized(self) -> bool:
        return self.client is not None

    def authorize(self) -> str:
        """发起 OAuth 授权，返回登录 URL."""
        self._require_sdk()
        self._oauth = stkclient.OAuth2()
        return self._oauth.get_signin_url()

    def finish_authorization(self, redirect_url: str) -> bool:
        """用浏览器回跳的完整 URL 完成授权，创建并保存 Client.

        注意：必须使用生成授权链接时同一个 OAuth2 实例（内部保存了
        PKCE verifier），因此授权与完成授权须先后调用本类方法。
        """
        self._require_sdk()
        if self._oauth is None:
            raise ApiPushError('请先点击「打开亚马逊授权页面」生成授权链接')
        try:
            client = self._oauth.create_client(redirect_url)
        except Exception as e:
            logger.error('授权失败: %s', e)
            return False
        if client is None:
            logger.error('授权失败：无法从回跳 URL 创建 Client')
            return False
        self.client = client
        self.save_state()
        logger.info('亚马逊账号授权成功')
        return True

    def get_devices(self) -> list:
        """获取用户 Kindle 设备列表（stkclient 直接返回 OwnedDevice 列表）."""
        self._require_client()
        try:
            owned = self.client.get_owned_devices()
        except Exception as e:
            logger.error('获取设备列表失败: %s', e)
            raise ApiPushError('获取设备列表失败: %s' % e) from e
        devices = []
        for d in owned or []:
            serial = getattr(d, 'device_serial_number', '')
            name = getattr(d, 'device_name', '') or serial
            if serial:
                devices.append(DeviceInfo(serial, name))
        self.devices = devices
        logger.info('获取设备列表成功，共 %d 台', len(devices))
        return devices

    def send_file(self, file_path: str, device_serial: str, title: str = None,
                  author: str = 'Kindle推送助手', fmt: str = None) -> bool:
        """推送文件到指定设备.

        :param fmt: 输入格式（如 PDF/EPUB），默认按扩展名推断
        """
        self._require_client()
        if not os.path.exists(file_path):
            raise ApiPushError('文件不存在: %s' % file_path)
        if not device_serial:
            raise ApiPushError('未选择目标设备')
        if not title:
            title = os.path.basename(file_path)
        if not fmt:
            fmt = os.path.splitext(file_path)[1].lstrip('.').upper() or 'PDF'
        try:
            self.client.send_file(
                file_path=Path(file_path),
                target_device_serial_numbers=[device_serial],
                author=author,
                title=title,
                format=fmt,
            )
        except Exception as e:
            logger.error('API 推送失败: %s', e)
            raise ApiPushError('API推送失败: %s' % e) from e
        logger.info('API 推送成功: %s → %s', os.path.basename(file_path), device_serial)
        return True

    def send_file_with_progress(self, file_path: str, device_serial: str,
                                progress_cb=None, title: str = None,
                                author: str = 'Kindle推送助手',
                                fmt: str = None) -> bool:
        """推送文件并回报真实上传进度（0-100）。

        直接调用 stkclient 的底层 api（get_upload_url / upload_file /
        send_to_kindle），让文件流经 _ProgressFile 逐块上报，避免大文件
        上传时进度条长时间静止看起来像卡死。若底层接口不可用则回退到
        标准 send_file（无进度）。
        """
        self._require_client()
        if not os.path.exists(file_path):
            raise ApiPushError('文件不存在: %s' % file_path)
        if not device_serial:
            raise ApiPushError('未选择目标设备')
        if not title:
            title = os.path.basename(file_path)
        if not fmt:
            fmt = os.path.splitext(file_path)[1].lstrip('.').upper() or 'PDF'

        try:
            from stkclient import api as _api
            signer = getattr(self.client, '_signer', None)
            if signer is None or not hasattr(_api, 'get_upload_url'):
                raise AttributeError('stkclient internals unavailable')
        except Exception:
            logger.warning('stkclient 底层接口不可用，回退到标准发送（无进度）')
            return self.send_file(file_path, device_serial, title=title,
                                  author=author, fmt=fmt)

        try:
            file_size = os.path.getsize(file_path)
            upload = _api.get_upload_url(signer, file_size)
            if progress_cb:
                progress_cb(2)
            with open(file_path, 'rb') as f:
                wrapped = _ProgressFile(f, file_size, progress_cb)
                _api.upload_file(upload.upload_url, file_size, wrapped)
            if progress_cb:
                progress_cb(98)
            _api.send_to_kindle(
                signer,
                upload.stk_token,
                [device_serial],
                author=author,
                title=title,
                format=fmt,
            )
            if progress_cb:
                progress_cb(100)
        except Exception as e:
            logger.error('API 推送失败: %s', e)
            raise ApiPushError('API推送失败: %s' % e) from e
        logger.info('API 推送成功: %s → %s', os.path.basename(file_path), device_serial)
        return True

    def save_state(self, path: str = None) -> bool:
        """保存 Client 授权状态，避免重复授权."""
        path = path or self.state_path
        if self.client is None:
            return False
        try:
            with open(path, 'w', encoding='utf-8') as f:
                self.client.dump(f)
            return True
        except Exception as e:
            logger.warning('授权状态保存失败: %s', e)
            return False

    def load_state(self, path: str = None) -> bool:
        """加载已保存的授权状态."""
        path = path or self.state_path
        if not STKCLIENT_AVAILABLE or not path or not os.path.exists(path):
            return False
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self.client = stkclient.Client.load(f)
            if self.client is not None:
                logger.info('已加载亚马逊账号授权状态')
                return True
        except Exception as e:
            logger.warning('授权状态加载失败（可能需要重新授权）: %s', e)
        self.client = None
        return False

    # ---------- internal ----------

    def _require_sdk(self):
        if not STKCLIENT_AVAILABLE:
            raise ApiPushError(INSTALL_HINT)

    def _require_client(self):
        self._require_sdk()
        if self.client is None:
            raise ApiPushError('授权已过期，请重新授权')
