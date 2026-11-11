#!/usr/bin/env python3
# Renders gifs/<pet>.gif (each pet going through all its moods, as in the status line)
# and gifs/<pet>-<mood>.gif (one mood only).
# Needs Pillow (pip install pillow) and a monospace font. Run: python3 make_gifs.py
import os, sys
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pet

MOODS = ["idle", "thinking", "working", "hectic", "asking", "failed", "confused",
         "startled", "surprised", "careful", "defensive", "embarrassed", "lecturing", "singing", "done", "sleeping", "chilling", "playing"]
FRAMES_PER_MOOD = 8
MS_PER_FRAME = 450
FONTS = ["/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]
BG, TEXT, DIM, LABEL = (30, 30, 36), (230, 230, 230), (130, 130, 140), (110, 110, 120)

def ansi256(code):
    n = int(code.split(";")[-1])
    if 16 <= n <= 231:
        n -= 16
        return tuple(0 if v == 0 else 55 + 40 * v for v in (n // 36, n // 6 % 6, n % 6))
    return TEXT

def main():
    font = next(ImageFont.truetype(f, 16) for f in FONTS if os.path.exists(f))
    cw = font.getbbox("M")[2]
    lh = 22
    lines = pet.load_lines()
    out_dir = os.path.join(pet.HERE, "gifs")
    os.makedirs(out_dir, exist_ok=True)
    for name in pet.all_pets():
        moods, color = pet.load_pet(name), ansi256(pet.COLORS.get(name, "0;0"))
        images = []
        for mood in MOODS:
            if mood not in moods:
                continue
            start = len(images)
            main_text, aside = (lines.get(mood) or [("", "")])[0]
            intro, loop = moods[mood]["order"]
            for t in range(max(FRAMES_PER_MOOD, len(intro) + len(loop))):  # one full cycle
                img = Image.new("RGB", (cw * 50, lh * 5 + 16), BG)
                d = ImageDraw.Draw(img)
                d.text((10, 6), mood, font=font, fill=LABEL)
                frame = pet.pick_frame(moods[mood], t)
                right = [(main_text, TEXT), (aside, DIM), ("", DIM), ("opus  ~/app", DIM)]
                for r in range(4):
                    y = 10 + lh * (r + 1)
                    d.text((10, y), frame[r] if r < len(frame) else "", font=font, fill=color)
                    d.text((10 + cw * (pet.WIDTH + 1), y), right[r][0], font=font, fill=right[r][1])
                images.append(img)
            one = images[start:]
            one[0].save(os.path.join(out_dir, f"{name}-{mood}.gif"), save_all=True,
                        append_images=one[1:], duration=MS_PER_FRAME, loop=0)
        path = os.path.join(out_dir, name + ".gif")
        images[0].save(path, save_all=True, append_images=images[1:], duration=MS_PER_FRAME, loop=0)
        print("wrote", path)

if __name__ == "__main__":
    main()
