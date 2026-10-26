"""Gera o ícone do app (build/minerador.ico e scripts/app/static/logo.png) desenhando o mesmo logo de static/logo.svg: cubo azul com lupa, fundo amarelo.
Roda no build: python build/make_icon.py"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent
SIZE = 1024  # desenha grande e reduz (suaviza as bordas)


def logo(size=SIZE):
    k = size / 64
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pts = lambda *p: [(x * k, y * k) for x, y in p]
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=14 * k, fill="#FFE600")
    d.polygon(pts((26, 12), (42, 21), (42, 39), (26, 48), (10, 39), (10, 21)), fill="#3483FA")
    d.polygon(pts((26, 12), (42, 21), (26, 30), (10, 21)), fill="#6aa5ff")
    d.polygon(pts((26, 30), (26, 48), (10, 39), (10, 21)), fill="#2968C8")
    cx, cy, r = 40 * k, 38 * k, 11 * k
    d.ellipse([cx - r - 2 * k, cy - r - 2 * k, cx + r + 2 * k, cy + r + 2 * k], fill="#333333")
    d.ellipse([cx - r + 2 * k, cy - r + 2 * k, cx + r - 2 * k, cy + r - 2 * k], fill="#f4f8ff")
    d.line([(48 * k, 46 * k), (57 * k, 55 * k)], fill="#333333", width=int(6 * k))
    d.ellipse([54.5 * k, 52.5 * k, 59.5 * k, 57.5 * k], fill="#333333")
    return im


if __name__ == "__main__":
    big = logo()
    big.resize((256, 256), Image.LANCZOS).save(OUT.parent / "scripts" / "app" / "static" / "logo.png")
    big.save(OUT / "minerador.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print("ícone gerado em", OUT / "minerador.ico")
