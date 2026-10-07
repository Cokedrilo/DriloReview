"""Genera el icono de la app desde el propio codigo.

    python make_icns.py build/DriloReview.icns          (macOS, necesita iconutil)
    python make_icns.py --ico build/DriloReview.ico     (Windows, cualquier sistema)

El dibujo es el de app_pixmap(). En macOS se le deja el margen de los iconos
del sistema; el .ico lleva varios tamanos (16 a 256) en PNG, para que en
Windows se vea nitido en el Explorador, la barra de tareas y el escritorio.
"""
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv[:1])
import driloreview  # noqa: E402

MARGEN_MAC = 100 / 1024      # la rejilla de iconos de macOS: 824 px de 1024


def icono(lado: int, margen: float) -> QPixmap:
    pm = QPixmap(lado, lado)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    m = lado * margen
    dentro = round(lado - 2 * m)
    p.drawPixmap(QRectF(m, m, dentro, dentro).toRect(), driloreview.app_pixmap(dentro))
    p.end()
    return pm


def png_bytes(pm: QPixmap) -> bytes:
    datos = QByteArray()
    buf = QBuffer(datos)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    return bytes(datos)


def write_ico(destino: Path):
    """Un .ico con una imagen PNG por tamano (lo admite Windows desde Vista)."""
    lados = (16, 24, 32, 48, 64, 128, 256)
    imagenes = [png_bytes(icono(l, 0.0)) for l in lados]
    cabecera = struct.pack("<HHH", 0, 1, len(lados))
    entradas, offset = b"", 6 + 16 * len(lados)
    for lado, png in zip(lados, imagenes):
        entradas += struct.pack("<BBBBHHII", lado % 256, lado % 256, 0, 0, 1, 32,
                                len(png), offset)
        offset += len(png)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(cabecera + entradas + b"".join(imagenes))
    print("icono:", destino)


def write_icns(destino: Path):
    with tempfile.TemporaryDirectory() as tmp:
        carpeta = Path(tmp) / "DriloReview.iconset"
        carpeta.mkdir()
        for lado in (16, 32, 128, 256, 512):
            icono(lado, MARGEN_MAC).save(str(carpeta / ("icon_%dx%d.png" % (lado, lado))))
            icono(lado * 2, MARGEN_MAC).save(str(carpeta / ("icon_%dx%d@2x.png" % (lado, lado))))
        destino.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["iconutil", "-c", "icns", str(carpeta), "-o", str(destino)],
                       check=True)
    print("icono:", destino)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--ico":
        write_ico(Path(args[1] if len(args) > 1 else "build/DriloReview.ico"))
    else:
        write_icns(Path(args[0] if args else "build/DriloReview.icns"))
