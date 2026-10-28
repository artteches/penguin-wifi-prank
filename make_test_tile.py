"""Тестовая плитка: какой цвет модулей лучше читается на светящемся белом.

Запуск:  py make_test_tile.py

Результат в dist/:
  qr-test-tile.3mf       белая основа + 3 цветных блока (оранжевый, синий, серый TPU) — если система берёт TPU
  qr-test-tile-pla.3mf   белая основа + оранжевый + синий (только PLA, без TPU)
  qr-test-tile-tpu.3mf   белая основа + только серый TPU (если TPU нельзя в твоей многоцветной системе —
                         печатай этот файл со сменой филамента вручную)
  qr-test-tile-preview.png  схема: что где лежит

Три колонки слева направо: 1) оранжевый (контроль — он уже не читался), 2) синий PLA, 3) тёмно-серый TPU.
В каждой колонке: сплошной квадрат 12×12 мм (для замера цвета) и «шахматка» 6×6 из квадратиков 2 мм —
такого же размера, как модули QR (смотрим, насколько чётко печатаются мелкие детали).
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from PIL import Image, ImageDraw

from make_qr import CELL as GRID          # сетка вкладыша 0.4 мм (не путать с CELL ниже — клетка шахматки 2 мм)
from make_qr import OUT, box, inlay_parts, volume, write_3mf

BASE_H, TOP_H = 2.0, 0.8          # как у настоящей плитки: основа 2 мм, модули 0.8 мм
SQ, CELL = 12.0, 2.0              # сплошной квадрат и клетка шахматки, мм
PAD = 3.0                         # поля и промежутки, мм
COLUMNS = [                       # (имя детали, материал, цвет для предпросмотра, extruder)
    ("orange", "Orange PLA", "#F57E24", 2),
    ("blue", "Blue PLA", "#2F5FD0", 3),
    ("gray-tpu", "Dark gray TPU", "#4A4A4A", 4),
]
W = PAD + len(COLUMNS) * (SQ + PAD)          # ширина плитки
H = PAD + SQ + PAD + SQ + PAD                # высота плитки: квадрат + шахматка


def column_tris(i):
    """Треугольники одного цветного блока: сплошной квадрат внизу и шахматка над ним."""
    x0 = PAD + i * (SQ + PAD)
    tris = []
    box(tris, x0, PAD, BASE_H, x0 + SQ, PAD + SQ, BASE_H + TOP_H)             # сплошной квадрат
    y0 = PAD + SQ + PAD
    for r in range(int(SQ / CELL)):
        for c in range(int(SQ / CELL)):
            if (r + c) % 2 == 0:
                box(tris, x0 + c * CELL, y0 + r * CELL, BASE_H,
                    x0 + (c + 1) * CELL, y0 + (r + 1) * CELL, BASE_H + TOP_H)
    return tris


def locked_tile_mask():
    """Одна колонка (шахматка 6×6 из клеток 2 мм + сплошной квадрат 12×12 мм) для варианта-вкладыша, клетки по 0.4 мм."""
    pad, sq, cell = 6, 30, 5                       # поле 2.4 мм, квадрат 12 мм, клетка шахматки 2 мм (в клетках сетки)
    rows, cols = pad + sq + pad + sq + pad, pad + sq + pad
    mask = [[False] * cols for _ in range(rows)]
    for r in range(pad, pad + sq):                 # шахматка сверху
        for c in range(pad, pad + sq):
            mask[r][c] = ((r - pad) // cell + (c - pad) // cell) % 2 == 0
    for r in range(pad + sq + pad, pad + sq + pad + sq):   # сплошной квадрат снизу
        for c in range(pad, pad + sq):
            mask[r][c] = True
    return mask


def main():
    OUT.mkdir(exist_ok=True)
    base = []
    box(base, 0, 0, 0, W, H, BASE_H)
    white = {"name": "base-white-glow", "tris": base, "material": "Glow white PLA", "color": "#E6F2DD", "extruder": 1}
    parts = [white]
    for i, (name, mat, color, ext) in enumerate(COLUMNS):
        parts.append({"name": name, "tris": column_tris(i), "material": mat, "color": color, "extruder": ext})
    write_3mf(OUT / "qr-test-tile.3mf", parts, "Colour contrast test tile")
    write_3mf(OUT / "qr-test-tile-pla.3mf", parts[:3], "Colour contrast test tile (PLA only)")
    tpu = parts[-1]
    write_3mf(OUT / "qr-test-tile-tpu.3mf", [white, {**tpu, "extruder": 2}], "Colour contrast test tile (TPU only)")

    # вариант-вкладыш: TPU вставлен в белую основу и зацеплен (TPU плохо липнет к PLA)
    lm = locked_tile_mask()
    lw, lt = inlay_parts(lm, top=BASE_H)
    write_3mf(OUT / "qr-test-tile-tpu-locked.3mf", [
        {"name": "base-white-glow", "tris": lw, "material": "Glow white PLA", "color": "#E6F2DD", "extruder": 1},
        {"name": "tpu-locked", "tris": lt, "material": "Dark gray TPU", "color": "#4A4A4A", "extruder": 2},
    ], "Colour contrast test tile (TPU inlay)")
    plate = len(lm) * len(lm[0]) * GRID * GRID * BASE_H
    print(f"Вкладыш: {len(lm[0]) * GRID:g} x {len(lm) * GRID:g} мм, белый {volume(lw):.0f} + TPU {volume(lt):.0f} = "
          f"{volume(lw) + volume(lt):.0f} мм³ из {plate:.0f}")

    # схема-предпросмотр (сверху, 20 пикселей на мм)
    s = 20
    img = Image.new("RGB", (int(W * s), int(H * s)), "#E6F2DD")
    d = ImageDraw.Draw(img)
    for i, (name, mat, color, ext) in enumerate(COLUMNS):
        x0 = PAD + i * (SQ + PAD)
        d.rectangle([x0 * s, (H - PAD - SQ) * s, (x0 + SQ) * s, (H - PAD) * s], fill=color)
        y0 = PAD + SQ + PAD
        for r in range(int(SQ / CELL)):
            for c in range(int(SQ / CELL)):
                if (r + c) % 2 == 0:
                    d.rectangle([(x0 + c * CELL) * s, (H - y0 - (r + 1) * CELL) * s,
                                 (x0 + (c + 1) * CELL) * s, (H - y0 - r * CELL) * s], fill=color)
    img.save(OUT / "qr-test-tile-preview.png")

    print(f"Плитка {W:.0f} x {H:.0f} мм, высота {BASE_H + TOP_H:.1f} мм")
    for p in parts:
        print(f"  {p['name']:16s} объём {volume(p['tris']):7.0f} мм³  (extruder {p['extruder']})")


if __name__ == "__main__":
    main()
