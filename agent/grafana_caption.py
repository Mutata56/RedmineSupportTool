# -*- coding: utf-8 -*-


import os
import time

_FONTS = (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf",
          r"C:\Windows\Fonts\calibri.ttf",

          "/usr/share/fonts/TTF/DejaVuSans.ttf",
          "/usr/share/fonts/dejavu/DejaVuSans.ttf",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
          "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
          "/usr/share/fonts/TTF/LiberationSans-Regular.ttf",
          "/usr/share/fonts/noto/NotoSans-Regular.ttf")


def _font_path():
    for p in _FONTS:
        if os.path.exists(p):
            return p
    return None


def _fit(draw, text, font, maxw):
    if draw.textlength(text, font=font) <= maxw:
        return text
    while text and draw.textlength(text + "…", font=font) > maxw:
        text = text[:-1]
    return text + "…"


def caption_png(path, dash_title, panel_title, role, site, period):

    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return path
    try:
        img = Image.open(path).convert("RGB")
        W, H = img.size
        s = 2 if W > 700 else 1
        fp = _font_path()
        if fp:
            f1 = ImageFont.truetype(fp, 15 * s)
            f2 = ImageFont.truetype(fp, 12 * s)
        else:
            f1 = f2 = ImageFont.load_default()
        pad, gap = 8 * s, 4 * s
        l1 = "%s · %s" % (dash_title, panel_title)
        parts = [site, "период %s" % period]
        if role:
            parts.append("роль %s" % role)
        parts.append("снято %s" % time.strftime("%Y-%m-%d %H:%M"))
        l2 = " · ".join(parts)
        h1 = f1.getbbox("Ag913Ёр")[3]
        h2 = f2.getbbox("Agpё")[3]
        strip = pad * 2 + h1 + gap + h2
        from PIL import Image as _I
        out = _I.new("RGB", (W, H + strip), (12, 13, 16))
        d = ImageDraw.Draw(out)
        d.text((pad, pad), _fit(d, l1, f1, W - 2 * pad), font=f1, fill=(225, 227, 233))
        d.text((pad, pad + h1 + gap), _fit(d, l2, f2, W - 2 * pad), font=f2, fill=(150, 156, 168))
        out.paste(img, (0, strip))
        out.save(path)
        return path
    except Exception:
        return path
