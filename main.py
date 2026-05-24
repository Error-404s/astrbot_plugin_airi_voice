from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W = 1360
BG_TOP = (252, 248, 255)
BG_BOTTOM = (244, 249, 255)
TEXT = (44, 51, 74)
ROOT = Path(r"f:\NORMAL\astrbot_plugin_airi_voice-master")
OUT = ROOT / "_preview"
OUT.mkdir(exist_ok=True)


def font(size, bold=False):
    candidates = [
        r"C:/Windows/Fonts/msyhbd.ttc" if bold else r"C:/Windows/Fonts/msyh.ttc",
        r"msyhbd.ttc" if bold else r"msyh.ttc",
        r"/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else r"/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        r"/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        r"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def gradient(img, top, bottom):
    d = ImageDraw.Draw(img)
    for y in range(img.size[1]):
        t = y / max(1, img.size[1] - 1)
        c = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        d.line((0, y, img.size[0], y), fill=c)


def sakura(draw, x, y, size, color):
    petal = max(6, size // 5)
    offsets = [(0, -size), (size - petal, -petal), (size // 2, size - petal), (-petal, size // 2), (size // 3, size // 3)]
    for ox, oy in offsets:
        draw.ellipse((x + ox, y + oy, x + ox + petal, y + oy + petal), fill=color)
    c = (x + size // 2, y + size // 2)
    draw.ellipse((c[0] - petal // 2, c[1] - petal // 2, c[0] + petal // 2, c[1] + petal // 2), fill=(255, 214, 221, 190))


def base(h):
    img = Image.new("RGBA", (W, h), BG_TOP)
    gradient(img, (255, 246, 250), (240, 248, 255))
    ov = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.ellipse((-120, -110, 340, 350), fill=(244, 114, 182, 68))
    d.ellipse((W - 390, 10, W + 70, 470), fill=(45, 212, 191, 64))
    d.ellipse((W * 0.26, -120, W * 0.64, 170), fill=(168, 85, 247, 44))
    d.ellipse((W * 0.62, 44, W * 0.96, 310), fill=(96, 165, 250, 52))
    d.ellipse((40, h - 240, 360, h + 80), fill=(251, 191, 36, 34))
    ov = ov.filter(ImageFilter.GaussianBlur(48))
    img = Image.alpha_composite(img, ov)
    d = ImageDraw.Draw(img)
    sakura(d, 44, 44, 54, (255, 182, 193, 160))
    sakura(d, W - 128, 56, 50, (255, 192, 203, 150))
    sakura(d, 120, h - 140, 48, (255, 179, 193, 120))
    sakura(d, W - 220, h - 160, 56, (255, 170, 186, 120))
    return img


# Voice list preview
items = ["Airi自我介绍", "MMJ!", "akt汪大吼", "ciallo～～", "emu汪大吼", "ena汪大吼", "hmm汪大吼", "hrk汪大吼"]
rows = 4
h = 160 + rows * 88 + (rows - 1) * 16 + 94
img = base(h)
d = ImageDraw.Draw(img)
header = Image.new("RGBA", (W, h), (0, 0, 0, 0))
hd = ImageDraw.Draw(header)
# transparent header (no frosted glass), keep subtle outline
hd.rounded_rectangle((38, 30, W - 38, 150), radius=36, fill=(255, 255, 255, 0), outline=(255, 255, 255, 110), width=2)
img = Image.alpha_composite(img, header)
d = ImageDraw.Draw(img)

tf = font(36, True)
sf = font(20)
bf = font(26, True)
ff = font(22)
hf = font(18)
d.text((70, 42), "AiriVoice 语音列表", font=tf, fill=(30, 41, 59))
d.text((70, 94), "第 1/2 页 · 共 42 个语音", font=sf, fill=(106, 122, 147))
d.rounded_rectangle((W - 392, 50, W - 244, 98), radius=24, fill=(255, 236, 244))
d.rounded_rectangle((W - 230, 50, W - 64, 98), radius=24, fill=(236, 250, 255))
d.text((W - 376, 60), "总数", font=sf, fill=(101, 116, 139))
d.text((W - 296, 58), "42", font=font(20, True), fill=(236, 72, 153))
d.text((W - 214, 60), "页码", font=sf, fill=(101, 116, 139))
d.text((W - 142, 58), "1/2", font=font(20, True), fill=(14, 165, 233))
accent = [(244, 114, 182), (96, 165, 250), (45, 212, 191), (168, 85, 247)]
padding_x = 68
gap_x = 24
gap_y = 16
card_w = (W - padding_x * 2 - gap_x) // 2
for i, name in enumerate(items):
    r = i // 2
    c = i % 2
    x1 = padding_x + c * (card_w + gap_x)
    y1 = 174 + r * (88 + gap_y)
    x2 = x1 + card_w
    y2 = y1 + 88
    ac = accent[i % 4]
    d.rounded_rectangle((x1, y1, x2, y2), radius=28, fill=(255, 255, 255, 255), outline=(232, 238, 246, 255), width=1)
    d.rounded_rectangle((x1, y1, x1 + 6, y2), radius=6, fill=ac)
    d.ellipse((x1 + 20, y1 + 24, x1 + 56, y1 + 60), fill=(ac[0], ac[1], ac[2], 10), outline=(ac[0], ac[1], ac[2], 180), width=2)
    d.text((x1 + 72, y1 + 20), name, font=bf, fill=TEXT)
    d.text((x1 + 72, y1 + 50), "直接输入关键词即可发送", font=hf, fill=(124, 138, 161))
footer_y = h - 94 + 10
d.rounded_rectangle((34, footer_y, W - 34, h - 18), radius=24, fill=(255, 255, 255, 230), outline=(232, 240, 248, 255), width=1)
d.text((68, footer_y + 18), "直接输入语音名称即可发送 · /voice.list [页码] 可翻页", font=ff, fill=(106, 122, 147))
d.text((W - 340, footer_y + 18), "下一页 /voice.list 2", font=ff, fill=(236, 72, 153))
img.save(OUT / "voice_list_preview.png")

# Help preview
sections = [
    ("快速说明", ["直接输入语音关键词即可发送对应语音。", "支持本地 voices/、网页上传、/voice.add 三种添加方式。"], (244, 114, 182)),
    ("触发模式", ["direct（默认）：直接输入关键词触发。", "prefix：需使用 #voice 关键词 触发。", "llm：由大模型通过工具调用。"], (96, 165, 250)),
    ("可用命令", ["/voice.list [页码] - 查看可用语音列表", "随机语音 或 随机发条语音 - 随机发送一条语音", "随机 关键词 - 在包含关键词的语音中随机发送", "/voice.help - 显示此帮助"], (45, 212, 191)),
    ("图片列表提示", ["可在插件配置中开启 list_as_image，让 /voice.list 以图片形式展示。", "分页可直接输入 /voice.list 2、/voice.list 3 继续翻页。"], (251, 191, 36)),
]
bodyf = font(20)
secf = font(25, True)
subf = font(20)
titlef = font(40, True)
footf = font(18)

# rough wrap helper
_temp = Image.new("RGBA", (W, 1400), BG_TOP)
_td = ImageDraw.Draw(_temp)
def wrap(text, maxw):
    out = []
    cur = ""
    for ch in text:
        cand = cur + ch
        if _td.textbbox((0, 0), cand, font=bodyf)[2] <= maxw:
            cur = cand
        else:
            if cur:
                out.append(cur)
            cur = ch
    if cur:
        out.append(cur)
    return out

wrapped = []
heights = []
for title, lines, ac in sections:
    ws = []
    for line in lines:
        ws.extend(wrap(line, W - 96 - 52))
    wrapped.append((title, ws, ac))
    heights.append(24 * 2 + 32 + 14 + len(ws) * 30 + max(0, len(ws) - 1) * 2)

hh = 156 + sum(heights) + 18 * (len(heights) - 1) + 84
img2 = base(hh)
# header with transparent background (no frosted glass)
ov = Image.new("RGBA", (W, hh), (0, 0, 0, 0))
dov = ImageDraw.Draw(ov)
dov.rounded_rectangle((38, 24, W - 38, 146), radius=36, fill=(255, 255, 255, 0), outline=(255, 255, 255, 110), width=2)
img2 = Image.alpha_composite(img2, ov)
d2 = ImageDraw.Draw(img2)
d2.text((70, 42), "AiriVoice 使用帮助", font=titlef, fill=(30, 41, 59))
d2.text((70, 94), "一张图快速看懂如何使用、分页和管理语音", font=subf, fill=(106, 122, 147))
d2.rounded_rectangle((W - 392, 50, W - 242, 98), radius=24, fill=(255, 236, 244))
d2.rounded_rectangle((W - 226, 50, W - 66, 98), radius=24, fill=(236, 250, 255))
d2.text((W - 376, 60), "状态", font=subf, fill=(101, 116, 139))
d2.text((W - 292, 58), "语音插件已就绪", font=font(20, True), fill=(236, 72, 153))
d2.text((W - 210, 60), "模式", font=subf, fill=(101, 116, 139))
d2.text((W - 142, 58), "direct", font=font(20, True), fill=(14, 165, 233))

y = 176
for title, ws, ac in wrapped:
    ch = 24 * 2 + 32 + 14 + len(ws) * 30 + max(0, len(ws) - 1) * 2
    d2.rounded_rectangle((48, y, 48 + (W - 96), y + ch), radius=28, fill=(255, 255, 255, 255), outline=(232, 238, 246, 255), width=1)
    d2.rounded_rectangle((48, y, 54, y + ch), radius=6, fill=ac)
    d2.ellipse((70, y + 22, 106, y + 58), fill=(ac[0], ac[1], ac[2], 10), outline=(ac[0], ac[1], ac[2], 180), width=2)
    d2.text((118, y + 20), title, font=secf, fill=(30, 41, 59))
    ty = y + 64
    for line in ws:
        d2.text((118, ty), "•", font=bodyf, fill=ac)
        d2.text((140, ty), line, font=bodyf, fill=TEXT)
        ty += 30
    y += ch + 18
fy = hh - 84 + 10
d2.rounded_rectangle((34, fy, W - 34, hh - 18), radius=24, fill=(255, 255, 255, 230), outline=(232, 240, 248, 255), width=1)
d2.text((68, fy + 18), "直接输入语音名称即可发送 · /voice.list 可查看语音列表", font=footf, fill=(106, 122, 147))
img2.save(OUT / "voice_help_preview.png")

print(str(OUT / 'voice_list_preview.png'))
print(str(OUT / 'voice_help_preview.png'))
