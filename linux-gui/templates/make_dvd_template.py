# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds a layered PSD template (opens in Affinity Photo) for DVD disc art.

Canvas = a square whose side equals the disc's outer diameter (2 x 58 mm), the same convention the
Disc Image Studio app/CLI uses, so the exported PNG drops straight into the app.
Run with a Python that has psd-tools + pillow:  python make_dvd_template.py out.psd
"""
import sys
from PIL import Image, ImageDraw
from psd_tools import PSDImage
from psd_tools.api.layers import PixelLayer, Group

SIZE = 4096                       # px; 4096 px = 116 mm  ->  35.31 px/mm (~897 dpi)
R_OUT, R_IN = 58.0, 24.0          # recording area (mm), standard 12 cm DVD
R_HOLE, R_CLAMP = 7.5, 16.5       # spindle hole radius, inner clamp edge
R_SAFE = 55.0                     # keep faces / key shapes inside this
BAND = 4.0                        # reserve for stored files (inner or outer ring)
PPM = SIZE / (2 * R_OUT)
C = SIZE / 2
SS = 2                            # supersample for smooth edges


def layer_img():
    return Image.new("RGBA", (SIZE * SS, SIZE * SS), (0, 0, 0, 0))


def finish(im):
    return im.resize((SIZE, SIZE), Image.LANCZOS)


def circle(d, r_mm, fill=None, outline=None, width_mm=0.25):
    r = r_mm * PPM * SS
    c = C * SS
    d.ellipse((c - r, c - r, c + r, c + r), fill=fill, outline=outline, width=max(1, int(width_mm * PPM * SS)))


def ring_fill(r_in, r_out, rgba):
    im = layer_img(); d = ImageDraw.Draw(im)
    circle(d, r_out, fill=rgba)
    ImageDraw.Draw(im)
    # punch the inside out
    hole = Image.new("L", im.size, 255); hd = ImageDraw.Draw(hole)
    r = r_in * PPM * SS; c = C * SS
    hd.ellipse((c - r, c - r, c + r, c + r), fill=0)
    im.putalpha(Image.composite(im.getchannel("A"), Image.new("L", im.size, 0), hole))
    return finish(im)


def ring_line(r_mm, rgba, w=0.3, dashed=False):
    im = layer_img(); d = ImageDraw.Draw(im)
    if not dashed:
        circle(d, r_mm, outline=rgba, width_mm=w)
    else:
        import math
        r = r_mm * PPM * SS; c = C * SS; n = 120
        for i in range(n):
            if i % 2 == 0:
                a0, a1 = 360 * i / n, 360 * (i + 1) / n
                d.arc((c - r, c - r, c + r, c + r), a0, a1, fill=rgba, width=max(1, int(w * PPM * SS)))
    return finish(im)


def outside_overlay():
    """Dim everything that will NOT be written: outside the outer ring and inside the inner ring."""
    im = layer_img(); d = ImageDraw.Draw(im)
    d.rectangle((0, 0, SIZE * SS, SIZE * SS), fill=(255, 70, 70, 80))
    keep = Image.new("L", im.size, 255); kd = ImageDraw.Draw(keep); c = C * SS
    ro, ri = R_OUT * PPM * SS, R_IN * PPM * SS
    kd.ellipse((c - ro, c - ro, c + ro, c + ro), fill=0)
    kd.ellipse((c - ri, c - ri, c + ri, c + ri), fill=255)
    im.putalpha(Image.composite(im.getchannel("A"), Image.new("L", im.size, 0), keep))
    return finish(im)


def cross():
    im = layer_img(); d = ImageDraw.Draw(im)
    w = max(1, int(0.2 * PPM * SS)); c = C * SS
    d.line((c, 0, c, SIZE * SS), fill=(255, 255, 255, 140), width=w)
    d.line((0, c, SIZE * SS, c), fill=(255, 255, 255, 140), width=w)
    return finish(im)


def main(out):
    psd = PSDImage.new("RGB", (SIZE, SIZE), color=(255, 255, 255))
    black = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 255))
    PixelLayer.frompil(black, psd, "BACKGROUND black (hide this for transparent)")
    PixelLayer.frompil(Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0)), psd, "ART - paint or place your artwork here")

    g = Group.new(psd, "GUIDES - hide before exporting", True)
    items = [
        ("Centre cross", cross()),
        ("Spindle hole 15 mm (not written)", ring_line(R_HOLE, (255, 255, 255, 230), 0.4)),
        ("Clamp area edge r=16.5 mm", ring_line(R_CLAMP, (180, 180, 180, 200), 0.25, dashed=True)),
        ("Safe area r=55 mm - keep faces and key shapes inside", ring_line(R_SAFE, (120, 255, 140, 230), 0.3, dashed=True)),
        (f"Files band OUTER {R_OUT - BAND:.0f}-{R_OUT:.0f} mm (reserve if files go to the outer ring)", ring_fill(R_OUT - BAND, R_OUT, (255, 220, 60, 70))),
        (f"Files band INNER {R_IN:.0f}-{R_IN + BAND:.0f} mm (reserve if files go to the inner ring)", ring_fill(R_IN, R_IN + BAND, (255, 220, 60, 70))),
        ("Recording area outer edge r=58 mm", ring_line(R_OUT, (80, 200, 255, 240), 0.35)),
        ("Recording area inner edge r=24 mm", ring_line(R_IN, (80, 200, 255, 240), 0.35)),
        ("NOT WRITTEN - outside the recording area (tinted red)", outside_overlay()),
    ]
    for name, im in items:
        PixelLayer.frompil(im, g, name)

    psd.save(out)
    print("saved", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "DVD-disc-template.psd")
