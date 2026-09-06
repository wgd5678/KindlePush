# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：单文件 exe（SRS 1.2 / 6）.

用法（在项目根目录）:
    .venv\\Scripts\\pyinstaller build\\kindle_push.spec --noconfirm
产物: dist\\KindlePushAssistant.exe
"""
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, \
    collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))

# 本地转换组件：RapidOCR 模型与配置为数据文件，pypdfium2 需要自带 DLL；
# mobi（KindleUnpack 移植）为纯 Python，收集全部子模块确保解包链路完整
converter_datas = collect_data_files('rapidocr_onnxruntime')
converter_binaries = collect_dynamic_libs('pypdfium2')
converter_hidden = (collect_submodules('rapidocr_onnxruntime')
                    + collect_submodules('mobi')
                    + ['loguru', 'unipath'])

a = Analysis(
    [os.path.join(ROOT, 'main.py')],
    pathex=[ROOT],
    binaries=converter_binaries,
    datas=[
        (os.path.join(ROOT, 'ui', 'styles.qss'), 'ui'),
        (os.path.join(ROOT, 'resources'), 'resources'),
    ] + converter_datas,
    hiddenimports=converter_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'pandas'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='KindlePushAssistant',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, 'resources', 'icon.ico'),
)
