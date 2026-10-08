"""Generate the Simple Auction app icon as assets/icon.png and assets/icon.ico."""

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256
BG = (47, 143, 157)  # theme accent
FG = (255, 255, 255)

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
draw.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=52, fill=BG + (255,))

# A simple gavel: a tilted head on a handle, over a sound block.
head = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
h = ImageDraw.Draw(head)
h.rounded_rectangle([70, 58, 150, 108], radius=12, fill=FG)  # head
h.rounded_rectangle([102, 100, 118, 182], radius=7, fill=FG)  # handle
head = head.rotate(35, resample=Image.Resampling.BICUBIC, center=(120, 120))
img.alpha_composite(head)
draw.rounded_rectangle([118, 186, 206, 206], radius=8, fill=FG)  # block

assets = Path(__file__).parent.parent / "assets"
assets.mkdir(exist_ok=True)

out_png = assets / "icon.png"
img.save(out_png, "PNG")
print(f"Saved {out_png}")

# ICO for Windows: standard sizes so Explorer and the taskbar stay sharp.
ico_sizes = [16, 32, 48, 256]
ico_frames = [img.resize((s, s), Image.Resampling.LANCZOS) for s in ico_sizes]
out_ico = assets / "icon.ico"
ico_frames[0].save(
    out_ico,
    format="ICO",
    sizes=[(s, s) for s in ico_sizes],
    append_images=ico_frames[1:],
)
print(f"Saved {out_ico}")
