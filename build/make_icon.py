# -*- coding: utf-8 -*-
"""生成程序图标 icon.ico / logo.png（开发工具脚本，运行时需要 Pillow）.

用法:
    .venv\\Scripts\\python build\\make_icon.py
"""
import os

from PIL import Image, ImageDraw

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
RES_DIR = os.path.join(ROOT, 'resources')


def render(size: int) -> Image.Image:
    """绘制图标：蓝色圆角底 + 白色书页 + 文字行 + Kindle 蓝点."""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 背景圆角矩形（品牌蓝）
    radius = int(size * 0.22)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius,
                        fill=(57, 100, 254, 255))

    # 白色书页
    s = size
    page_l, page_t = int(s * 0.26), int(s * 0.20)
    page_r, page_b = int(s * 0.74), int(s * 0.80)
    d.rounded_rectangle([page_l, page_t, page_r, page_b],
                        radius=int(s * 0.05), fill=(255, 255, 255, 255))

    # 文字行（灰色）
    line_color = (190, 198, 216, 255)
    lw = int(s * 0.035)
    left = page_l + int(s * 0.07)
    right = page_r - int(s * 0.07)
    for i in range(4):
        y = page_t + int(s * 0.10) + i * int(s * 0.115)
        rr = right - (int(s * 0.12) if i == 3 else 0)
        d.rounded_rectangle([left, y, rr, y + lw],
                            radius=lw // 2, fill=line_color)

    # 底部 Kindle 蓝点
    dot_r = int(s * 0.05)
    cx, cy = s // 2, page_b - int(s * 0.10)
    d.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
              fill=(57, 100, 254, 255))
    return img


def main():
    os.makedirs(RES_DIR, exist_ok=True)
    icon_sizes = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
    images = [render(sz) for sz in icon_sizes]
    ico_path = os.path.join(RES_DIR, 'icon.ico')
    images[-1].save(ico_path, format='ICO',
                    sizes=[(im.width, im.height) for im in images],
                    append_images=images[:-1])
    render(128).save(os.path.join(RES_DIR, 'logo.png'), format='PNG')
    print('icon saved:', ico_path)


if __name__ == '__main__':
    main()
