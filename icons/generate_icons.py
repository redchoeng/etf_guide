"""PWA 아이콘 생성 (Pillow 사용)."""
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow 미설치, 기본 아이콘 생성")
    # 1x1 pixel PNG fallback
    import struct, zlib
    def make_png(size, path):
        # Minimal valid PNG: solid color
        w, h = size, size
        raw = b''
        for y in range(h):
            raw += b'\x00'  # filter byte
            for x in range(w):
                # Gradient blue-green
                r = 33
                g = 150
                b = 243
                a = 255
                raw += bytes([r, g, b, a])
        compressed = zlib.compress(raw)

        def chunk(ctype, data):
            c = ctype + data
            return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

        sig = b'\x89PNG\r\n\x1a\n'
        ihdr = struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)

        with open(path, 'wb') as f:
            f.write(sig)
            f.write(chunk(b'IHDR', ihdr))
            f.write(chunk(b'IDAT', compressed))
            f.write(chunk(b'IEND', b''))
        print(f"  Created {path} ({size}x{size})")

    make_png(192, "icons/icon-192.png")
    make_png(512, "icons/icon-512.png")
    exit()

for size in [192, 512]:
    img = Image.new('RGBA', (size, size), (33, 150, 243, 255))
    draw = ImageDraw.Draw(img)

    # Draw house emoji-like shape
    cx, cy = size // 2, size // 2
    s = size // 4

    # Background circle
    draw.ellipse([s//2, s//2, size - s//2, size - s//2], fill=(255, 255, 255, 230))

    # House roof (triangle)
    roof = [(cx, cy - s), (cx - s, cy - s//4), (cx + s, cy - s//4)]
    draw.polygon(roof, fill=(244, 67, 54))

    # House body (rectangle)
    draw.rectangle([cx - s*3//4, cy - s//4, cx + s*3//4, cy + s], fill=(121, 85, 72))

    # Door
    dw = s // 3
    draw.rectangle([cx - dw//2, cy + s//4, cx + dw//2, cy + s], fill=(62, 39, 35))

    # Window
    ww = s // 4
    draw.rectangle([cx + s//4, cy - s//8, cx + s//4 + ww, cy + s//8 + ww], fill=(255, 235, 59))

    # Dollar sign
    try:
        font_size = s // 2
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        font = ImageFont.load_default()
    draw.text((cx - s*3//4, cy + s + s//8), "$", fill=(76, 175, 80), font=font)

    img.save(f"icons/icon-{size}.png")
    print(f"Created icon-{size}.png")
