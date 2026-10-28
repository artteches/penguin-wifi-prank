"""Делает QR-код для 3D-печати в два цвета (STL).

Запуск:  py make_qr.py https://твой-сайт.example/        (адрес игры)
         py make_qr.py URL --module 2.2 --base 2.0 --height 0.8

Результат в dist/:
  qr-base-white-glow.stl   основа (светящийся белый PLA)
  qr-modules-orange.stl    тёмные квадратики QR (оранжевый PLA)
  qr-preview.png           как оно будет выглядеть
Обе детали в одних координатах: в слайсере загружай их ВМЕСТЕ
(как одну сборку / assembly) и назначь каждой свой филамент.
"""
import argparse
import socket
import struct
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

sys.stdout.reconfigure(encoding="utf-8")   # чтобы русский текст не превращался в кракозябры

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from PIL import Image, ImageDraw

QUIET = 4          # тихая зона (quiet zone) в модулях — без неё QR не читается
OUT = Path(__file__).parent / "dist"


def lan_ip() -> str:
    """IP компьютера в домашней сети — чтобы проверить код с телефона."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def box(tris, x0, y0, z0, x1, y1, z1):
    """Добавляет параллелепипед (12 треугольников)."""
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]   # нормали наружу
    for a, b, c, d in faces:
        tris.append((v[a], v[b], v[c]))
        tris.append((v[a], v[c], v[d]))


def write_stl(path, tris, name):
    with open(path, "wb") as f:
        f.write(name.encode()[:80].ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        for a, b, c in tris:
            f.write(struct.pack("<12fH", 0, 0, 0, *a, *b, *c, 0))


def volume(tris):
    """Объём детали, мм³. Положительный = треугольники повёрнуты наружу (деталь «правильная»)."""
    return sum(a[0] * (b[1] * c[2] - b[2] * c[1]) + a[1] * (b[2] * c[0] - b[0] * c[2])
               + a[2] * (b[0] * c[1] - b[1] * c[0]) for a, b, c in tris) / 6


def mesh_xml(tris):
    """Треугольники → сетка 3MF (одинаковые вершины склеиваем, файл получается меньше)."""
    idx, verts, faces = {}, [], []
    for tri in tris:
        ids = []
        for p in tri:
            k = tuple(round(c, 4) for c in p)
            if k not in idx:
                idx[k] = len(verts)
                verts.append(k)
            ids.append(idx[k])
        faces.append(ids)
    vx = "".join(f'<vertex x="{x:g}" y="{y:g}" z="{z:g}"/>' for x, y, z in verts)
    tr = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces)
    return f"<mesh><vertices>{vx}</vertices><triangles>{tr}</triangles></mesh>"


def write_3mf(path, parts, title):
    """Один файл 3MF с несколькими деталями-цветами (для многоцветной печати).

    parts — список словарей: name, tris, material, color (#RRGGBB), extruder (1, 2, ...).
    Цвета лежат в basematerials (их понимают слайсеры), а Metadata/model_settings.config
    подсказывает Bambu Studio / Orca, какой филамент (extruder) чей.
    """
    mats = "".join(f'<base name="{escape(p["material"])}" displaycolor="{p["color"]}FF"/>' for p in parts)
    objs = "".join(
        f'<object id="{i + 2}" type="model" pid="1" pindex="{i}" name="{escape(p["name"])}">{mesh_xml(p["tris"])}</object>'
        for i, p in enumerate(parts))
    items = "".join(f'<item objectid="{i + 2}"/>' for i in range(len(parts)))
    model = ('<?xml version="1.0" encoding="UTF-8"?>'
             '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             f'<metadata name="Title">{escape(title)}</metadata>'
             f'<resources><basematerials id="1">{mats}</basematerials>{objs}</resources>'
             f'<build>{items}</build></model>')
    settings = ('<?xml version="1.0" encoding="UTF-8"?><config>' + "".join(
        f'<object id="{i + 2}"><metadata key="name" value="{escape(p["name"])}"/>'
        f'<metadata key="extruder" value="{p["extruder"]}"/></object>' for i, p in enumerate(parts)) + '</config>')
    content_types = ('<?xml version="1.0" encoding="UTF-8"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
                     '<Default Extension="config" ContentType="text/xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
        z.writestr("Metadata/model_settings.config", settings)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", default=f"http://{lan_ip()}:8000/")
    ap.add_argument("--module", type=float, default=2.0, help="размер одного квадратика, мм")
    ap.add_argument("--base", type=float, default=2.0, help="толщина основы, мм")
    ap.add_argument("--height", type=float, default=0.8, help="высота синих модулей, мм")
    a = ap.parse_args()

    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, border=0)
    qr.add_data(a.url)
    qr.make(fit=True)
    grid = qr.get_matrix()
    n = len(grid)
    m = a.module
    size = (n + 2 * QUIET) * m

    # основа
    base = []
    box(base, 0, 0, 0, size, size, a.base)

    # синие модули: склеиваем соседние в полоски по строкам
    blue = []
    for r, row in enumerate(grid):
        y0 = (QUIET + (n - 1 - r)) * m
        c = 0
        while c < n:
            if row[c]:
                s = c
                while c < n and row[c]:
                    c += 1
                box(blue, (QUIET + s) * m, y0, a.base, (QUIET + c) * m, y0 + m, a.base + a.height)
            else:
                c += 1

    OUT.mkdir(exist_ok=True)
    write_stl(OUT / "qr-base-white-glow.stl", base, "qr base")
    write_stl(OUT / "qr-modules-orange.stl", blue, "qr modules")
    write_3mf(OUT / "qr-penguin-wifi.3mf", [
        {"name": "base-white-glow", "tris": base, "material": "Glow white PLA", "color": "#E6F2DD", "extruder": 1},
        {"name": "modules-orange", "tris": blue, "material": "Orange PLA", "color": "#E8590C", "extruder": 2},
    ], f"QR {a.url}")
    print(f"Объём деталей: основа {volume(base):.0f} мм³, модули {volume(blue):.0f} мм³ (должны быть > 0)")

    # картинка-предпросмотр
    px = 16
    img = Image.new("RGB", ((n + 2 * QUIET) * px,) * 2, "#e9f3e4")
    d = ImageDraw.Draw(img)
    for r, row in enumerate(grid):
        for c, v in enumerate(row):
            if v:
                d.rectangle([(QUIET + c) * px, (QUIET + r) * px,
                             (QUIET + c + 1) * px - 1, (QUIET + r + 1) * px - 1], fill="#e8590c")
    img.save(OUT / "qr-preview.png")

    print(f"Адрес в коде : {a.url}  ({len(a.url)} символов)")
    print(f"Версия QR    : {qr.version}  ({n}x{n} модулей)")
    print(f"Размер плитки: {size:.1f} x {size:.1f} мм, высота {a.base + a.height:.1f} мм")
    if m < 1.6:
        print("ВНИМАНИЕ: модуль меньше 1.6 мм — сопло 0.4 может печатать плохо.")


main()
