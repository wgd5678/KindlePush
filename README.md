# Kindle 推送助手（KindlePushAssistant）

中文 | [English](README_EN.md)

Windows 桌面应用：把本地 PDF / EPUB / DOCX / TXT / RTF 文档推送到个人 Kindle。
支持把 PDF 本地转换为 EPUB（内置离线 OCR，扫描版也能转）再经 API 推送，
或通过亚马逊邮件云端转换（→ KFX），支持转换前的本地备份下载。

## 功能特性

- **文件管理**：按钮多选添加、拖拽添加、列表展示（名称/大小/格式/状态）、删除与清空
- **三种推送方式**：
  - **邮件推送**：主题随「转换为 Kindle 阅读格式」开关变化（`Convert` / 文件名）；适合 < 50MB 文件
  - **API 推送**：亚马逊官方 Send to Kindle 通道（stkclient / OAuth2），突破 50MB 限制
  - **USB 传输**：自动检测 Kindle 盘符，复制到 `documents` 目录（不转换）
- **Kindle 阅读模式转换（免邮箱）**：勾选后 API 推送时，PDF 在本地转换为 EPUB——文字版直接提取（书签自动分章），扫描版调用内置离线中文 OCR（RapidOCR）逐页识别；转换结果经 API 推送，亚马逊云端自动转成可重排的 Kindle 格式。邮件推送仍使用亚马逊云端转换（主题 Convert）
- **本地下载**：单文件另存为（右键）或批量下载选中文件
- **配置管理**：JSON 存储；邮箱密码使用 Fernet 加密；支持测试 SMTP 连接
- **日志与历史**：按天滚动日志、自动清理、一键导出；推送历史展示最近 5 条
- **打包**：PyInstaller 单文件 exe，免安装分发

## 快速开始（开发模式）

要求 Windows + Python 3.10+。

```bat
cd KindlePush
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

## 使用说明

### 邮件推送

1. 打开「设置 → 邮件推送配置」，填写发件邮箱、SMTP 服务器/端口、密码或授权码、Kindle 邮箱（常见邮箱的 SMTP 会自动填充）。
2. 点击「测试连接」确认无误后保存。
3. **重要**：先到亚马逊「管理我的内容和设备 → 首选项 → 个人文档设置 → 已批准的个人文档邮件列表」添加你的发件邮箱，否则会被拒收。
4. 添加文件，选择「邮件推送」，点击「开始推送」。

### PDF 转换为 Kindle 阅读格式

「推送选项」中的 **转换为 Kindle 阅读格式** 复选框（默认勾选）控制是否触发格式转换：

- **API 推送（免邮箱）**：PDF 先在本地转换成 EPUB，再照常走 API 推送，亚马逊把 EPUB 自动转成可重排的 Kindle 格式（可调字体、适应屏幕）。文字版 PDF 用 pypdfium2 直接提取文字并按书签分章；扫描版 PDF 自动调用内置 RapidOCR 逐页识别（约每页 1~3 秒）。转换结果保存在程序 temp 目录，开启「推送成功自动删除本地临时文件」后推送成功即清理。
- **AZW3/AZW/MOBI/PRC（Kindle 原生格式）**：亚马逊 Send-to-Kindle（邮件与 API）已停止接受这类格式，因此走 API 推送时软件会始终先在本地转换成 EPUB（基于 KindleUnpack 解包，保留原书目录与样式，纯格式转换无需 OCR），不受上述复选框影响；走 USB 则原样拷贝即可直接阅读；邮件通道不支持并会给出提示。带 DRM 保护的购书无法转换，会直接报错。
- **邮件推送**：邮件主题为 `Convert`，使用亚马逊云端转换（需配置邮箱）。
- **取消勾选**：原样推送，PDF 在 Kindle 上保持原始版式；USB 传输不做转换。
- **兜底**：本地转换失败时自动回退为按原样推送并在历史中注明，不会导致推送失败。

### API 推送

1. 点击「设置 → API推送配置 → 重新授权」，按弹窗提示在浏览器登录亚马逊账号。
2. 授权完成后复制浏览器地址栏的完整回跳 URL，粘贴回弹窗并确认。
3. 选择目标设备后推送。授权状态会持久保存，无需重复登录。

### USB 传输

1. 用数据线连接 Kindle（连接后设备进入磁盘模式）。
2. 推送方式选「USB传输」，软件自动识别盘符（卷标含 Kindle 优先），必要时点「刷新」。
3. 文件将被复制到 Kindle 的 `documents` 目录；安全弹出设备后即可阅读。

## 打包发布

```bat
.venv\Scripts\python build\make_icon.py
.venv\Scripts\pyinstaller build\kindle_push.spec --noconfirm
```

产物为 `dist\KindlePushAssistant.exe`（单文件，直接分发；交付时可重命名为「Kindle推送助手.exe」）。

## 目录结构

```
KindlePush/
├── main.py                 # 程序入口
├── app.py                  # 主应用类 / 应用上下文
├── requirements.txt
├── ui/                     # UI 模块（主窗口/设置/授权/日志 + QSS）
├── core/                   # 核心业务（文件管理/推送引擎/邮件/API/USB/历史）
├── models/                 # 数据模型（FileTask / 配置）
├── utils/                  # 日志 / 加密 / 辅助函数
├── resources/              # 图标资源
├── build/                  # PyInstaller spec 与图标生成脚本
├── logs/  temp/            # 运行时创建
└── config.json             # 首次运行自动生成（密码加密存储）
```

## 常见问题

- **邮件推送被拒收**：发件邮箱未加入亚马逊已批准列表，或主题不是 `Convert`（勾选转换时本程序自动设置）。
- **邮件推送提示文件过大**：附件超过 50MB 上限，请改用 API 推送。
- **API 授权失败**：确认粘贴的是授权完成后地址栏的完整回跳 URL。
- **检测不到 Kindle**：确认数据线支持数据传输（部分充电线不行），且设备已挂载为磁盘。
- **扫描版 PDF 转换慢**：本地转换需逐页 OCR（约每页 1~3 秒），几百页的书需要几分钟到十几分钟，属正常现象。
- **依赖说明**：直接 `pip install stkclient` 即可（`import stkclient`）；本地转换依赖 `pypdfium2` 与 `rapidocr-onnxruntime`（见 requirements.txt，onnxruntime 需锁定 1.20 系列）。
