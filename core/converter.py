# -*- coding: utf-8 -*-
"""本地 PDF → EPUB 转换器（无需邮箱，转换后经 API 推送）.

管线：
  1. pypdfium2 逐页判断文字层：
     - 文字页：按 text rect 聚合成段落；
     - 扫描页（无文字层）：整页渲染为图片，RapidOCR 识别出文字行再聚合成段落；
  2. 章节划分：优先使用 PDF 书签（outline），无书签时按页数分块；
  3. 用标准库 zipfile 打包为 EPUB 2（mimetype / container.xml / OPF / NCX / XHTML）。
     EPUB 经 API 推送后，亚马逊云端会自动转换成可重排的 Kindle 格式。

授权说明：pypdfium2（Apache-2.0）与 RapidOCR（Apache-2.0）均为宽松开源协议。
"""
import logging
import os
import shutil
import threading
import uuid
import zipfile
from html import escape
from xml.sax.saxutils import escape as xml_escape

from utils.helpers import get_app_dir

logger = logging.getLogger('kindle_push.converter')

# ---------------------------------------------------------------------------
# 依赖可用性（缺失时仅禁用扫描版 OCR，文字版转换不受影响）
# ---------------------------------------------------------------------------
try:
    import pypdfium2 as pdfium
    PDFIUM_AVAILABLE = True
except ImportError:
    pdfium = None
    PDFIUM_AVAILABLE = False

try:
    from rapidocr_onnxruntime import RapidOCR
    OCR_AVAILABLE = True
except ImportError:
    RapidOCR = None
    OCR_AVAILABLE = False

try:
    import mobi as mobi_lib
    MOBI_AVAILABLE = True
except ImportError:
    mobi_lib = None
    MOBI_AVAILABLE = False

OCR_LOCK = threading.Lock()
_OCR_ENGINE = None

# 文字页判定阈值：一页文本字符数低于该值视为扫描页
TEXT_PAGE_MIN_CHARS = 20
# OCR 渲染目标宽度（像素）
OCR_RENDER_WIDTH = 1600
# 无书签时按页数分块的块大小
FALLBACK_CHUNK_PAGES = 30
MAX_CHAPTERS = 400


class ConvertError(Exception):
    """本地转换失败（含中文用户提示）."""


def _get_ocr_engine():
    """懒加载 RapidOCR 引擎（模型加载约 2~5 秒，进程内只加载一次）."""
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        with OCR_LOCK:
            if _OCR_ENGINE is None:
                if not OCR_AVAILABLE:
                    raise ConvertError('未检测到 OCR 组件（rapidocr-onnxruntime），'
                                       '无法识别扫描版 PDF')
                logger.info('初始化 RapidOCR 引擎…')
                _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


# ---------------------------------------------------------------------------
# 第 1 步：逐页提取段落
# ---------------------------------------------------------------------------

def _page_has_text(page) -> bool:
    try:
        tp = page.get_textpage()
        return tp.count_chars() >= TEXT_PAGE_MIN_CHARS
    except Exception:
        return False


def _extract_text_paragraphs(page):
    """文字页：按 text rect 组行、按行距聚合成段落.

    :return: [{'style': 'heading'|'para', 'text': str}, ...]
    """
    tp = page.get_textpage()
    n = tp.count_rects()
    lines = []          # (top, bottom, text)
    for i in range(n):
        try:
            rect = tp.get_rect(i)
            text = tp.get_text_bounded(*rect).strip()
        except Exception:
            continue
        if not text:
            continue
        left, bottom, right, top = rect
        # 与上一行同基线（同一物理行被拆成多个 rect）→ 合并
        if lines:
            p_top, p_bottom, p_text = lines[-1]
            mid = (top + bottom) / 2.0
            p_mid = (p_top + p_bottom) / 2.0
            height = max(1.0, top - bottom, p_top - p_bottom)
            if abs(mid - p_mid) < 0.45 * height:
                lines[-1] = (max(p_top, top), min(p_bottom, bottom), p_text + text)
                continue
        lines.append((top, bottom, text))

    # 按 PDF 坐标自上而下排序（top 越大越靠上）
    lines.sort(key=lambda t: -t[0])
    return _cluster_lines([(l[2], l[0], l[1]) for l in lines])


def _ocr_page_paragraphs(page, progress=None):
    """扫描页：渲染为图片 → OCR → 聚合成段落."""
    import numpy as np

    engine = _get_ocr_engine()
    width = page.get_size()[0]
    scale = min(4.0, max(1.5, OCR_RENDER_WIDTH / max(1.0, width)))
    bitmap = page.render(scale=scale)
    pil = bitmap.to_pil().convert('RGB')
    # RapidOCR 接受 numpy 数组（不接受 PIL 对象）
    result, _elapse = engine(np.asarray(pil))
    if not result:
        return []
    lines = []
    for item in result:
        try:
            box, text, score = item[0], str(item[1]).strip(), float(item[2])
        except (ValueError, TypeError, IndexError):
            continue
        if not text or score < 0.35:
            continue
        ys = [p[1] for p in box]
        lines.append((text, min(ys), max(ys)))     # 图片坐标：y 向下递增
    lines.sort(key=lambda t: t[1])
    return _cluster_lines(lines, ocr=True)


def _cluster_lines(lines, ocr=False):
    """把 [(text, top, bottom), ...]（已按阅读顺序排序）聚合成段落.

    采用页面自适应阈值：以相邻行间距的中位数为基准，超过其约 1.45 倍
    （且超过绝对上限 1.1 倍行高约束）视为段落间隔；孤短行且无句末
    标点 → 视为标题。
    """
    if not lines:
        return []
    gaps = []
    heights = []
    for (text1, top1, bottom1), (text2, top2, bottom2) in zip(lines, lines[1:]):
        gap = (top2 - bottom2) if ocr else (bottom1 - top2)   # 行间空白
        gaps.append(max(0.0, gap))
        heights.append(max(1.0, top1 - bottom1))
    heights.append(max(1.0, lines[-1][1] - lines[-1][2]))
    median_gap = _median(gaps) if gaps else 0.0
    median_h = _median(heights) or 1.0
    if median_gap <= 0:
        threshold = (0.9 if ocr else 0.55) * median_h
    else:
        threshold = max(median_gap * 1.45, median_gap + 2.0)
    threshold = min(threshold, 1.1 * median_h)   # 绝对上限，防止阈值失控

    paragraphs = []
    buf_text = None
    buf_top = buf_bottom = 0.0

    def flush():
        nonlocal buf_text
        if buf_text and buf_text.strip():
            text = buf_text.strip()
            style = 'para'
            if len(text) <= 30 and not _ends_sentence(text):
                style = 'heading'
            paragraphs.append({'style': style, 'text': text})
        buf_text = None

    for text, top, bottom in lines:
        if buf_text is not None:
            gap = (top - buf_bottom) if ocr else (buf_bottom - top)
            if gap > threshold:
                flush()
        if buf_text is None:
            buf_text = text
        else:
            buf_text += text
        buf_top, buf_bottom = top, bottom
    flush()
    return paragraphs


def _median(values):
    values = sorted(values)
    n = len(values)
    if not n:
        return 0.0
    mid = n // 2
    if n % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2.0


def _ends_sentence(text: str) -> bool:
    return bool(text) and text[-1] in '。！？，、；：…"）)》】'


# ---------------------------------------------------------------------------
# 第 2 步：章节划分
# ---------------------------------------------------------------------------

def _read_toc(doc, page_count):
    """读取 PDF 书签，返回 [(title, start_page)]（按页码排序、去重）."""
    entries = []
    try:
        try:                       # 兼容 v4（max_depth/max_items）与 v5（无参）签名
            toc_iter = doc.get_toc(max_depth=4)
        except TypeError:
            toc_iter = doc.get_toc()
        for bm in toc_iter:
            try:
                dest = bm.get_dest()
                idx = dest.get_index() if dest is not None else None
            except Exception:
                idx = None
            if idx is None or not (0 <= idx < page_count):
                continue
            title = (bm.get_title() or '').strip()
            if title:
                entries.append((title, int(idx)))
    except Exception as e:
        logger.warning('读取 PDF 书签失败（忽略，改用整书分块）: %s', e)
        return []
    entries.sort(key=lambda t: t[1])
    # 同页多条书签只保留第一条
    result = []
    for title, idx in entries:
        if result and result[-1][1] == idx:
            continue
        if len(result) >= MAX_CHAPTERS:
            break
        result.append((title, idx))
    return result


def _build_chapter_plan(toc, page_count):
    """生成 [{title, start, end}]，end 为 exclusive 页码."""
    if not toc:
        plan = []
        start = 0
        part = 1
        while start < page_count:
            end = min(start + FALLBACK_CHUNK_PAGES, page_count)
            plan.append({'title': '第 %d 部分' % part, 'start': start, 'end': end})
            start = end
            part += 1
        return plan or [{'title': '正文', 'start': 0, 'end': max(1, page_count)}]

    plan = []
    if toc[0][1] > 0:
        plan.append({'title': '卷首', 'start': 0, 'end': toc[0][1]})
    for i, (title, start) in enumerate(toc):
        end = toc[i + 1][1] if i + 1 < len(toc) else page_count
        end = max(end, start + 1)
        plan.append({'title': title, 'start': start, 'end': min(end, page_count)})
    return plan


# ---------------------------------------------------------------------------
# 第 3 步：EPUB 打包（标准库实现，零依赖）
# ---------------------------------------------------------------------------

XHTML_TMPL = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" '
    '"http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">\n'
    '<html xmlns="http://www.w3.org/1999/xhtml">\n'
    '<head>\n'
    '  <title>{title}</title>\n'
    '  <link rel="stylesheet" type="text/css" href="../style.css"/>\n'
    '</head>\n'
    '<body>\n{body}</body>\n'
    '</html>\n'
)

STYLE_CSS = """body { margin: 5% 6%; line-height: 1.7; }
h2 { font-size: 1.4em; text-align: center; margin: 1em 0 0.9em 0; }
h3 { font-size: 1.12em; margin: 1.1em 0 0.3em 0; }
p { text-indent: 2em; margin: 0 0 0.15em 0; }
"""


def _chapter_xhtml(ch_title, paragraphs):
    parts = ['  <h2>%s</h2>' % escape(ch_title)]
    for para in paragraphs:
        text = escape(para['text'])
        if para['style'] == 'heading':
            parts.append('  <h3>%s</h3>' % text)
        else:
            parts.append('  <p>%s</p>' % text)
    if len(parts) == 1:
        parts.append('  <p>（本页无可用文本）</p>')
    return XHTML_TMPL.format(title=escape(ch_title), body='\n'.join(parts) + '\n')


def _build_epub(out_path, title, author, chapter_titles, chapter_xhtmls):
    """打包 EPUB 2：mimetype 首条 STORED，其余 DEFLATED."""
    book_id = 'urn:uuid:%s' % uuid.uuid4()
    meta_author = ''
    if author:
        meta_author = '    <dc:creator opf:role="aut">%s</dc:creator>\n' % xml_escape(author)

    manifest, spine, navpoints = [], [], []
    for i, ch_title in enumerate(chapter_titles):
        item_id = 'ch%03d' % (i + 1)
        href = 'text/chapter-%03d.xhtml' % (i + 1)
        manifest.append('    <item id="%s" href="%s" media-type="application/xhtml+xml"/>'
                        % (item_id, href))
        spine.append('    <itemref idref="%s"/>' % item_id)
        navpoints.append(
            '    <navPoint id="nav%03d" playOrder="%d">\n'
            '      <navLabel><text>%s</text></navLabel>\n'
            '      <content src="%s"/>\n'
            '    </navPoint>' % (i + 1, i + 1, xml_escape(ch_title), href))

    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
        'unique-identifier="bookid">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:opf="http://www.idpf.org/2007/opf">\n'
        '    <dc:title>%s</dc:title>\n'
        '%s'
        '    <dc:language>zh</dc:language>\n'
        '    <dc:identifier id="bookid">%s</dc:identifier>\n'
        '  </metadata>\n'
        '  <manifest>\n'
        '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>\n'
        '    <item id="css" href="style.css" media-type="text/css"/>\n'
        '%s\n'
        '  </manifest>\n'
        '  <spine toc="ncx">\n%s\n  </spine>\n'
        '</package>\n'
    ) % (xml_escape(title), meta_author, book_id,
         '\n'.join(manifest), '\n'.join(spine))

    ncx = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        '  <head>\n'
        '    <meta name="dtb:uid" content="%s"/>\n'
        '    <meta name="dtb:depth" content="1"/>\n'
        '  </head>\n'
        '  <docTitle><text>%s</text></docTitle>\n'
        '  <navMap>\n%s\n  </navMap>\n'
        '</ncx>\n'
    ) % (book_id, xml_escape(title), '\n'.join(navpoints))

    container = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        '  <rootfiles>\n'
        '    <rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/>\n'
        '  </rootfiles>\n'
        '</container>\n'
    )

    with zipfile.ZipFile(out_path, 'w') as zf:
        zf.writestr(zipfile.ZipInfo('mimetype'), 'application/epub+zip',
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr('META-INF/container.xml', container, zipfile.ZIP_DEFLATED)
        zf.writestr('OEBPS/content.opf', opf, zipfile.ZIP_DEFLATED)
        zf.writestr('OEBPS/toc.ncx', ncx, zipfile.ZIP_DEFLATED)
        zf.writestr('OEBPS/style.css', STYLE_CSS, zipfile.ZIP_DEFLATED)
        for i, xhtml in enumerate(chapter_xhtmls):
            zf.writestr('OEBPS/text/chapter-%03d.xhtml' % (i + 1), xhtml,
                        zipfile.ZIP_DEFLATED)


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------

def convert_pdf_to_epub(pdf_path: str, out_path: str = None,
                        progress_cb=None, ocr: bool = True,
                        author: str = '') -> str:
    """把 PDF 转换为 EPUB.

    :param progress_cb: callable(percent:int) 0-100（可选）
    :param ocr: 遇到扫描页时是否使用 OCR（需要 rapidocr-onnxruntime）
    :param author: 元数据作者（可选）
    :return: 生成的 EPUB 路径
    :raises ConvertError: 打不开 PDF、扫描版且无 OCR 组件等
    """
    if not PDFIUM_AVAILABLE:
        raise ConvertError('未检测到 pypdfium2 组件，无法本地转换')
    if not os.path.exists(pdf_path):
        raise ConvertError('文件不存在: %s' % pdf_path)

    def report(percent):
        if progress_cb:
            try:
                progress_cb(max(0, min(100, int(percent))))
            except Exception:
                pass

    try:
        doc = pdfium.PdfDocument(pdf_path)
    except Exception as e:
        raise ConvertError('无法打开 PDF（文件可能已加密或损坏）: %s' % e) from e

    try:
        page_count = len(doc)
        if page_count < 1:
            raise ConvertError('PDF 没有可用的页面')

        text_flags = []
        report(2)
        for i in range(page_count):
            text_flags.append(_page_has_text(doc[i]))
        scanned_pages = text_flags.count(False)
        if scanned_pages == page_count and not (ocr and OCR_AVAILABLE):
            raise ConvertError('该 PDF 为扫描版（未检测到文字层），'
                               '本地转换需要 OCR 组件支持')

        toc = _read_toc(doc, page_count)
        plan = _build_chapter_plan(toc, page_count)
        # 每章聚合段落
        chapter_paras = [{'title': ch['title'], 'paras': []} for ch in plan]
        page_to_ch = {}
        for ci, ch in enumerate(plan):
            for pg in range(ch['start'], min(ch['end'], page_count)):
                page_to_ch[pg] = ci

        for i in range(page_count):
            page = doc[i]
            if text_flags[i]:
                paras = _extract_text_paragraphs(page)
            elif ocr and OCR_AVAILABLE:
                try:
                    paras = _ocr_page_paragraphs(page)
                except ConvertError:
                    raise
                except Exception as e:
                    logger.warning('第 %d 页 OCR 失败（跳过该页）: %s', i + 1, e)
                    paras = []
            else:
                paras = []
            ci = page_to_ch.get(i, 0)
            chapter_paras[ci]['paras'].extend(paras)
            report(2 + 88 * (i + 1) / page_count)

        title = os.path.splitext(os.path.basename(pdf_path))[0]
        if out_path is None:
            out_dir = os.path.join(get_app_dir(), 'temp')
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, '%s.epub' % title)
        chapter_xhtmls = [_chapter_xhtml(ch['title'], ch['paras'])
                          for ch in chapter_paras]
        chapter_titles = [ch['title'] for ch in chapter_paras]
        _build_epub(out_path, title, author, chapter_titles, chapter_xhtmls)
        report(100)
        logger.info('本地转换完成: %s → %s（%d 页，扫描页 %d，章节 %d）',
                    os.path.basename(pdf_path), out_path,
                    page_count, scanned_pages, len(chapter_titles))
        return out_path
    finally:
        try:
            doc.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# AZW3 / MOBI → EPUB（Kindle 原生重排版格式，解包即得，无 OCR）
# ---------------------------------------------------------------------------

# Kindle 原生格式：亚马逊 Send-to-Kindle（邮件与 API）已停止接受，
# 无线推送必须先本地转 EPUB；USB 通道可原样拷贝。
KINDLE_BOOK_EXTS = ('.azw3', '.azw', '.mobi', '.prc')

_IMAGE_MEDIA_TYPES = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
    '.gif': 'image/gif', '.svg': 'image/svg+xml', '.bmp': 'image/bmp',
}


def is_kindle_book_file(path: str) -> bool:
    """判断文件是否为 Kindle 原生格式（azw3/azw/mobi/prc）."""
    return os.path.splitext(path or '')[1].lower() in KINDLE_BOOK_EXTS


def _build_epub_mobi7(out_path, title, author, html_bytes, image_dir, images):
    """把旧版 MOBI（mobi7）解包出的 book.html + Images 打包成 EPUB."""
    book_id = 'urn:uuid:%s' % uuid.uuid4()
    meta_author = ''
    if author:
        meta_author = '    <dc:creator opf:role="aut">%s</dc:creator>\n' % xml_escape(author)

    image_items, image_files = [], []
    for name in images:
        ext = os.path.splitext(name)[1].lower()
        media = _IMAGE_MEDIA_TYPES.get(ext, 'application/octet-stream')
        image_items.append('    <item id="img%s" href="Images/%s" media-type="%s"/>'
                           % (len(image_items), xml_escape(name), media))
        image_files.append((name, os.path.join(image_dir, name)))

    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
        'unique-identifier="bookid">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:opf="http://www.idpf.org/2007/opf">\n'
        '    <dc:title>%s</dc:title>\n'
        '%s'
        '    <dc:language>zh</dc:language>\n'
        '    <dc:identifier id="bookid">%s</dc:identifier>\n'
        '  </metadata>\n'
        '  <manifest>\n'
        '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>\n'
        '    <item id="book" href="book.html" media-type="text/html"/>\n'
        '%s\n'
        '  </manifest>\n'
        '  <spine toc="ncx">\n    <itemref idref="book"/>\n  </spine>\n'
        '</package>\n'
    ) % (xml_escape(title), meta_author, book_id, '\n'.join(image_items))

    ncx = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        '  <head><meta name="dtb:uid" content="%s"/></head>\n'
        '  <docTitle><text>%s</text></docTitle>\n'
        '  <navMap>\n'
        '    <navPoint id="nav001" playOrder="1">\n'
        '      <navLabel><text>正文</text></navLabel>\n'
        '      <content src="book.html"/>\n'
        '    </navPoint>\n'
        '  </navMap>\n'
        '</ncx>\n'
    ) % (book_id, xml_escape(title))

    container = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        '  <rootfiles>\n'
        '    <rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/>\n'
        '  </rootfiles>\n'
        '</container>\n'
    )

    with zipfile.ZipFile(out_path, 'w') as zf:
        zf.writestr(zipfile.ZipInfo('mimetype'), 'application/epub+zip',
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr('META-INF/container.xml', container, zipfile.ZIP_DEFLATED)
        zf.writestr('OEBPS/content.opf', opf, zipfile.ZIP_DEFLATED)
        zf.writestr('OEBPS/toc.ncx', ncx, zipfile.ZIP_DEFLATED)
        zf.writestr('OEBPS/book.html', html_bytes, zipfile.ZIP_DEFLATED)
        for name, src in image_files:
            try:
                with open(src, 'rb') as f:
                    zf.writestr('OEBPS/Images/%s' % name, f.read(),
                                zipfile.ZIP_DEFLATED)
            except OSError as e:
                logger.warning('MOBI 图片缺失（跳过）: %s → %s', name, e)


def convert_azw3_to_epub(input_path: str, out_path: str = None,
                         progress_cb=None, author: str = '') -> str:
    """把 AZW3/AZW/MOBI/PRC 转换为 EPUB.

    KF8（azw3）直接由解包器生成完整 EPUB（保留原书目录与样式）；
    旧版 MOBI 解包为 book.html + 图片后重新打包。

    :param progress_cb: callable(percent:int) 0-100（可选）
    :param author: 元数据作者（可选）
    :return: 生成的 EPUB 路径
    :raises ConvertError: 带 DRM 保护、解包失败、文件不存在等
    """
    if not MOBI_AVAILABLE:
        raise ConvertError('未检测到 mobi 解包组件，无法转换 AZW3/MOBI 文件')
    if not os.path.exists(input_path):
        raise ConvertError('文件不存在: %s' % input_path)

    def report(percent):
        if progress_cb:
            try:
                progress_cb(max(0, min(100, int(percent))))
            except Exception:
                pass

    title = os.path.splitext(os.path.basename(input_path))[0]
    if out_path is None:
        out_dir = os.path.join(get_app_dir(), 'temp')
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, '%s.epub' % title)

    report(5)
    tempdir = None
    try:
        try:
            tempdir, result = mobi_lib.extract(input_path)
        except Exception as e:
            raise ConvertError(
                '无法解包该书（可能是带 DRM 保护的亚马逊购书，或文件已损坏）: %s' % e) from e
        report(55)

        low = (result or '').lower()
        if low.endswith('.epub'):
            # KF8：解包器已生成完整 EPUB，校验后直接采用
            with zipfile.ZipFile(result) as zf:
                if zf.testzip() is not None:
                    raise ConvertError('解包生成的 EPUB 内部有损坏条目')
                entries = len(zf.namelist())
            shutil.copyfile(result, out_path)
            report(100)
            logger.info('本地转换完成: %s → %s（KF8，EPUB 条目 %d）',
                        os.path.basename(input_path), out_path, entries)
        elif low.endswith('.html'):
            # 旧版 MOBI：book.html + Images 重新打包
            base_dir = os.path.dirname(result)
            with open(result, 'rb') as f:
                html_bytes = f.read()
            image_dir = os.path.join(base_dir, 'Images')
            images = []
            if os.path.isdir(image_dir):
                images = sorted(n for n in os.listdir(image_dir)
                                if os.path.isfile(os.path.join(image_dir, n)))
            _build_epub_mobi7(out_path, title, author,
                              html_bytes, image_dir, images)
            report(100)
            logger.info('本地转换完成: %s → %s（MOBI7，图片 %d 张）',
                        os.path.basename(input_path), out_path, len(images))
        else:
            raise ConvertError('该文件解包后为不支持的类型: %s'
                               % os.path.basename(result))
        return out_path
    finally:
        if tempdir:
            shutil.rmtree(tempdir, ignore_errors=True)
