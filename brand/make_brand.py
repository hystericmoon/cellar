#!/usr/bin/env python3
"""Generate Cellar's brand assets: the door mark, the wordmark (Funnel Display, outlined),
the macOS app icon set, the favicon and the menu bar icons.

Needs fontTools (pip install fonttools) and rsvg-convert (brew install librsvg).
Run from anywhere: python3 brand/make_brand.py
"""
import os, subprocess
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.varLib.instancer import instantiateVariableFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FONT = os.path.join(HERE, "fonts", "FunnelDisplay[wght].ttf")

# ---- the door ---------------------------------------------------------------
# A low arched door, 56 wide x 54 tall, with four steps cut out of it (even-odd holes).
DOOR = "M0 54V28A28 28 0 0 1 56 28V54Z"
STEPS = [(8, 48, 50), (13, 43, 42), (18, 38, 34), (23, 33, 26)]  # (x1, x2, y centre) in door space


def pill(x1, x2, y, h=5):
    r = h / 2
    return (f"M{x1} {y - r}H{x2}A{r} {r} 0 0 1 {x2} {y + r}H{x1}A{r} {r} 0 0 1 {x1} {y - r}Z")


DOOR_PATH = DOOR + "".join(pill(*s) for s in STEPS)
DOOR_OUTLINE = "M2.5 51.5V28A25.5 25.5 0 0 1 53.5 28V51.5Z"  # for the "no phone" menu bar icon


def mark_svg(fill="currentColor"):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 56 54">'
            f'<path fill="{fill}" fill-rule="evenodd" d="{DOOR_PATH}"/></svg>\n')


# ---- the wordmark -----------------------------------------------------------
def word_path(text="Cellar", weight=600, size=100, tracking=-0.012):
    font = instantiateVariableFont(TTFont(FONT), {"wght": weight})
    upm = font["head"].unitsPerEm
    cmap, gs, hmtx = font.getBestCmap(), font.getGlyphSet(), font["hmtx"]
    # pair kerning is left out on purpose: "Cellar" sets well without it at these sizes
    s = size / upm
    asc = font["OS/2"].sCapHeight
    pen = SVGPathPen(gs)
    x = 0
    for ch in text:
        g = cmap[ord(ch)]
        gs[g].draw(TransformPen(pen, (s, 0, 0, -s, x, asc * s)))
        x += hmtx[g][0] * s + tracking * size
    x -= tracking * size
    return pen.getCommands(), x, asc * s, font["OS/2"].sTypoDescender * s


def wordmark_svg(fill="currentColor", door_fill=None):
    d, w, cap, _ = word_path()
    # door height matches cap height + a little; sits on the baseline
    dh = cap * 1.06
    k = dh / 54
    dw = 56 * k
    gap = cap * 0.30
    total = dw + gap + w
    door = f'<path fill="{door_fill or fill}" fill-rule="evenodd" transform="translate(0 {cap - dh:.2f}) scale({k:.4f})" d="{DOOR_PATH}"/>'
    word = f'<path fill="{fill}" transform="translate({dw + gap:.2f} 0)" d="{d}"/>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 {cap - dh:.2f} {total:.2f} {dh:.2f}">'
            f'{door}{word}</svg>\n'), (total, dh)


# ---- app icon -----------------------------------------------------------------
def app_icon_svg():
    # macOS icon grid: 1024 canvas, 824 tile at 100, corner radius ~185.
    k = 430 / 56
    dw, dh = 56 * k, 54 * k
    x, y = (1024 - dw) / 2, (1024 - dh) / 2 + 18
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
<defs>
 <linearGradient id="t" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2a2a2c"/><stop offset="1" stop-color="#0e0e0f"/></linearGradient>
 <linearGradient id="d" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#e6e6e6"/></linearGradient>
 <filter id="s" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="18" stdDeviation="22" flood-color="#000" flood-opacity=".28"/></filter>
</defs>
<rect x="100" y="100" width="824" height="824" rx="185" fill="url(#t)"/>
<rect x="100.5" y="100.5" width="823" height="823" rx="184.5" fill="none" stroke="#fff" stroke-opacity=".10"/>
<path filter="url(#s)" fill="url(#d)" fill-rule="evenodd" transform="translate({x:.1f} {y:.1f}) scale({k:.4f})" d="{DOOR_PATH}"/>
</svg>
'''


def menubar_svg(connected):
    if connected:
        body = f'<path fill="#000" fill-rule="evenodd" d="{DOOR_PATH}"/>'
    else:
        body = f'<path fill="none" stroke="#000" stroke-width="5" d="{DOOR_OUTLINE}"/>'
    # 18 pt square with the door centred; padding keeps it optically the size of SF Symbols
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-8 -9 72 72">{body}</svg>\n'


def write(path, text):
    with open(path, "w") as f:
        f.write(text)


def png(svg, out, size):
    subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), "-o", out, svg], check=True)


def main():
    out = os.path.join(HERE, "assets")
    os.makedirs(out, exist_ok=True)
    write(os.path.join(out, "cellar-mark.svg"), mark_svg())
    write(os.path.join(out, "cellar-mark-black.svg"), mark_svg("#111111"))
    write(os.path.join(out, "cellar-mark-white.svg"), mark_svg("#ffffff"))
    wm, _ = wordmark_svg()
    write(os.path.join(out, "cellar-wordmark.svg"), wm)
    write(os.path.join(out, "cellar-wordmark-black.svg"), wordmark_svg("#111111")[0])
    write(os.path.join(out, "cellar-wordmark-white.svg"), wordmark_svg("#ffffff")[0])
    icon = os.path.join(out, "app-icon.svg")
    write(icon, app_icon_svg())
    png(icon, os.path.join(out, "app-icon-1024.png"), 1024)

    iconset = os.path.join(ROOT, "mac", "AppIcon.iconset")
    for pt in (16, 32, 128, 256, 512):
        png(icon, os.path.join(iconset, f"icon_{pt}x{pt}.png"), pt)
        png(icon, os.path.join(iconset, f"icon_{pt}x{pt}@2x.png"), pt * 2)

    for state in ("connected", "disconnected"):
        svg = os.path.join(out, f"menubar-{state}.svg")
        write(svg, menubar_svg(state == "connected"))
        name = "MenubarTemplate" if state == "connected" else "MenubarOffTemplate"
        png(svg, os.path.join(ROOT, "mac", f"{name}.png"), 18)
        png(svg, os.path.join(ROOT, "mac", f"{name}@2x.png"), 36)

    # favicon: black door in a light browser, white in a dark one (the page recolours it per theme)
    fav = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-2 -3 60 60"><style>path{{fill:#111}}'
           f'@media (prefers-color-scheme:dark){{path{{fill:#fff}}}}</style>'
           f'<path fill-rule="evenodd" d="{DOOR_PATH}"/></svg>\n')
    write(os.path.join(out, "favicon.svg"), fav)
    d, w, cap, _ = word_path()
    print("door path:", DOOR_PATH)
    print("wordmark size:", round(w, 1), "x", round(cap, 1))


if __name__ == "__main__":
    main()
