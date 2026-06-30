"""
make_icon.py — generate icon.ico for SheetForge.exe.

A spreadsheet grid on the forge's accent purple (#7C6AF7, the same accent
forge_build.py stamps into workbooks). Run:  python make_icon.py
Produces a multi-resolution icon.ico (16-256 px). Requires Pillow.
"""
from PIL import Image, ImageDraw

ACCENT    = (124, 106, 247, 255)   # 7C6AF7 brand accent
ACCENT_DK = (88,  72, 196, 255)    # header band
SHEET     = (255, 255, 255, 255)
GRID      = (214, 212, 232, 255)
CELL_TINT = (124, 106, 247, 70)    # faint "data" cell

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# rounded app-tile background
d.rounded_rectangle([8, 8, S - 8, S - 8], radius=48, fill=ACCENT)

# the white "sheet"
x0, y0, x1, y1 = 54, 40, 202, 216
d.rounded_rectangle([x0, y0, x1, y1], radius=16, fill=SHEET)

# header band (round the top, flatten where it meets the grid)
hdr = 34
d.rounded_rectangle([x0, y0, x1, y0 + hdr], radius=16, fill=ACCENT_DK)
d.rectangle([x0, y0 + hdr - 16, x1, y0 + hdr], fill=ACCENT_DK)

# grid
cols, rows = 3, 4
gx = (x1 - x0) / cols
gy = (y1 - (y0 + hdr)) / rows
# one tinted data cell, top-left of the grid body
d.rectangle([x0 + 4, y0 + hdr + 2, x0 + gx - 2, y0 + hdr + gy - 2], fill=CELL_TINT)
for c in range(1, cols):
    x = x0 + gx * c
    d.line([x, y0 + hdr, x, y1], fill=GRID, width=3)
for r in range(1, rows):
    y = y0 + hdr + gy * r
    d.line([x0, y, x1, y], fill=GRID, width=3)

img.save("icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote icon.ico")
