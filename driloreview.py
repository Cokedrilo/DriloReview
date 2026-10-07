#!/usr/bin/env python3
"""
DriloReview - draw over images and export them as one PDF.  By Drilo.

La parte de anotar de DriloBoard, suelta: arrastras imagenes (o carpetas) a la
ventana, cada una es una pagina, dibujas encima con las herramientas del editor
de DriloBoard y al final sale un solo PDF con todas, en el orden de la tira.

Los archivos originales no se tocan nunca: los dibujos se guardan como objetos
(trazos, flechas, texto...) en coordenadas de la imagen, en memoria o en un
proyecto .driloreview, y solo se "funden" con la imagen dentro del PDF, donde
ademas van como vectores, nitidos a cualquier zoom.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

from PySide6.QtCore import (QByteArray, QEvent, QMarginsF, QMimeData, QObject, QPointF, QRectF,
                            QRunnable, QSettings, QSize, QSizeF, Qt, QThreadPool, QTimer,
                            Signal, Slot)
from PySide6.QtGui import (QAction, QColor, QFont, QFontMetricsF, QIcon, QImage,
                           QImageIOHandler, QImageReader,
                           QKeySequence, QPageLayout, QPageSize, QPainter, QPainterPath,
                           QPainterPathStroker, QPalette, QPdfWriter, QPen, QPixmap,
                           QShortcut)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox,
                               QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QGraphicsItem, QGraphicsPathItem,
                               QGraphicsPixmapItem, QGraphicsScene, QGraphicsView,
                               QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QProgressDialog, QPushButton, QSlider, QSplitter,
                               QStackedWidget, QStyledItemDelegate, QStyleOptionViewItem,
                               QToolButton, QVBoxLayout, QWidget)

APP_NAME = "DriloReview"
APP_AUTHOR = "Drilo"
VERSION = "1.1.0"
PROJECT_EXT = ".driloreview"
PROJECT_EXTS = (PROJECT_EXT, ".drilonalisis")   # tambien los de cuando se llamaba DriloNalisis
PROJECT_FILTER = "DriloReview project (%s)" % " ".join("*" + e for e in PROJECT_EXTS)
MAC = sys.platform == "darwin"
WINDOWS = sys.platform == "win32"
SHAPES_MIME = "application/x-driloreview-shapes"     # elementos copiados
PASTED_DAYS = 30                    # las imagenes pegadas sin proyecto se borran a los 30 dias
UNDO_LIMIT = 60
THUMB_SIZE = 320                    # lado mayor de la miniatura de la tira (Retina)
MAX_PIXELS = 80_000_000             # el lienzo reduce las imagenes mas grandes
PAGE_ROLE = int(Qt.ItemDataRole.UserRole) + 1
SHAPE_ROLE = int(Qt.ItemDataRole.UserRole) + 2


def _writable(carpeta: Path) -> bool:
    try:
        prueba = carpeta / (".driloreview-%s" % uuid.uuid4().hex[:8])
        prueba.write_bytes(b"")
        prueba.unlink()
        return True
    except OSError:
        return False


def data_dir() -> Path:
    """Donde van los ajustes y las imagenes pegadas.

    En Windows, la version empaquetada es portable como DriloBoard: junto al
    .exe si esa carpeta se puede escribir (un USB, por ejemplo). Si no, y en
    macOS y Linux, la carpeta de datos del usuario. Ni registro ni plist.
    Las pruebas lo apuntan a una carpeta temporal con DRILOREVIEW_DATA."""
    otra = os.environ.get("DRILOREVIEW_DATA")
    if otra:
        d = Path(otra)
    elif WINDOWS and getattr(sys, "frozen", False) and _writable(Path(sys.executable).parent):
        d = Path(sys.executable).parent
    elif WINDOWS:
        d = Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME
    elif MAC:
        d = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        d = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def pasted_dir() -> Path:
    d = data_dir() / "pasted"
    d.mkdir(exist_ok=True)
    return d


def is_pasted(path: str) -> bool:
    """Si la imagen salio del portapapeles y aun no tiene proyecto propio."""
    norm = lambda r: os.path.normcase(os.path.abspath(r))
    return norm(os.path.dirname(path)) == norm(str(pasted_dir()))


def prune_pasted(en_uso: set, dias: int = PASTED_DAYS):
    """Borra las imagenes pegadas viejas: las que se guardaron en un proyecto
    ya tienen su copia junto a el."""
    limite = time.time() - dias * 86400
    for f in pasted_dir().glob("*.png"):
        try:
            if str(f) not in en_uso and f.stat().st_mtime < limite:
                f.unlink()
        except OSError:
            pass


def app_settings() -> QSettings:
    return QSettings(str(data_dir() / "settings.ini"), QSettings.Format.IniFormat)


def keys_text(texto: str) -> str:
    """Los atajos como los ve cada sistema: en Mac, Ctrl es Cmd."""
    if not MAC:
        return texto
    return texto.replace("Ctrl+Shift+", "⇧⌘").replace("Ctrl+", "⌘").replace("Shift+", "⇧")


def supported_exts() -> set:
    exts = {"." + bytes(f).decode().lower() for f in QImageReader.supportedImageFormats()}
    exts.discard(".pdf")            # un PDF no es una pagina de imagen
    exts.discard(".svgz")
    return exts


# --------------------------------------------------------------------------- #
#  Tema (el mismo de DriloBoard)
# --------------------------------------------------------------------------- #
THEMES = {
    "dark": {"canvas": "#141516", "dim": "#8b8e95", "ink": "#c8cad0",
             "bg": "#202124", "panel": "#18191b", "raised": "#2b2c30",
             "hover": "#35373c", "border": "#383a40", "text": "#e8e9ec",
             "accent": "#f2a93b", "accent_hover": "#f7b95a",
             "on_accent": "#1b1b1d", "accent_soft": "#4a3a1c"},
    "light": {"canvas": "#dfe0e3", "dim": "#6b6e76", "ink": "#3a3c42",
              "bg": "#f1f2f4", "panel": "#ffffff", "raised": "#ffffff",
              "hover": "#eceef1", "border": "#d3d5da", "text": "#1d1e21",
              "accent": "#e59a1f", "accent_hover": "#d98a0b",
              "on_accent": "#1b1b1d", "accent_soft": "#fbe7c3"},
}
_theme = "dark"


def theme_color(clave: str) -> str:
    return THEMES[_theme][clave]


def system_theme() -> str:
    if QApplication.styleHints().colorScheme() == Qt.ColorScheme.Light:
        return "light"
    return "dark"


def fusion_palette(nombre: str) -> QPalette:
    t = THEMES[nombre]
    oscuro = nombre == "dark"
    pal = QPalette()
    R, G = QPalette.ColorRole, QPalette.ColorGroup
    for rol, color in ((R.Window, t["bg"]), (R.WindowText, t["text"]),
                       (R.Base, t["panel"]), (R.AlternateBase, t["raised"]),
                       (R.Button, t["raised"]), (R.ButtonText, t["text"]),
                       (R.Text, t["text"]), (R.ToolTipBase, t["raised"]),
                       (R.ToolTipText, t["text"]), (R.PlaceholderText, t["dim"]),
                       (R.Highlight, t["accent"]), (R.HighlightedText, t["on_accent"]),
                       (R.Link, t["accent"]),
                       (R.Light, "#3a3c42" if oscuro else "#ffffff"),
                       (R.Midlight, "#313338" if oscuro else "#eceef1"),
                       (R.Mid, t["border"]),
                       (R.Dark, "#101113" if oscuro else "#a8abb2"),
                       (R.Shadow, "#000000" if oscuro else "#707070")):
        pal.setColor(rol, QColor(color))
    for rol in (R.WindowText, R.ButtonText, R.Text):
        pal.setColor(G.Disabled, rol, QColor(t["dim"]))
    return pal


def build_qss(nombre: str) -> str:
    return """
QToolTip { background:%(raised)s; color:%(text)s; border:1px solid %(border)s;
           padding:4px 6px; border-radius:4px; }
QStatusBar { color:%(dim)s; }
QStatusBar::item { border:none; }
QMenu { background:%(panel)s; border:1px solid %(border)s; border-radius:8px; padding:5px; }
QMenu::item { padding:6px 22px 6px 14px; border-radius:5px; color:%(text)s; }
QMenu::item:selected { background:%(accent_soft)s; color:%(text)s; }
QMenu::item:disabled { color:%(dim)s; }
QMenu::separator { height:1px; background:%(border)s; margin:5px 8px; }
QMenuBar { background:transparent; }
QMenuBar::item { padding:4px 9px; border-radius:5px; background:transparent; }
QMenuBar::item:selected { background:%(hover)s; }

QPushButton { background:%(raised)s; color:%(text)s; border:1px solid %(border)s;
              border-radius:6px; padding:5px 12px; min-height:18px; }
QPushButton:hover { background:%(hover)s; }
QPushButton:pressed { background:%(border)s; }
QPushButton:disabled { color:%(dim)s; background:transparent; }
QPushButton[primary="true"] { background:%(accent)s; color:%(on_accent)s;
              border:1px solid %(accent)s; font-weight:600; }
QPushButton[primary="true"]:hover { background:%(accent_hover)s; }
QPushButton[primary="true"]:disabled { background:transparent; color:%(dim)s;
              border:1px solid %(border)s; }

QToolButton { background:transparent; border:1px solid transparent;
              border-radius:6px; padding:3px; color:%(text)s; }
QToolButton:hover { background:%(hover)s; }
QToolButton:checked { background:%(accent_soft)s; border:1px solid %(accent)s; }
QToolButton:disabled { color:%(dim)s; }

QCheckBox { spacing:8px; color:%(text)s; }
QSlider::groove:horizontal { height:4px; background:%(border)s; border-radius:2px; }
QSlider::sub-page:horizontal { background:%(accent)s; border-radius:2px; }
QSlider::handle:horizontal { background:%(raised)s; border:2px solid %(accent)s;
              width:12px; height:12px; margin:-7px 0; border-radius:8px; }
QSlider::handle:horizontal:hover { background:%(accent)s; }

QScrollBar:vertical { background:transparent; width:12px; margin:2px; }
QScrollBar:horizontal { background:transparent; height:12px; margin:2px; }
QScrollBar::handle:vertical { background:%(border)s; border-radius:4px; min-height:30px; }
QScrollBar::handle:horizontal { background:%(border)s; border-radius:4px; min-width:30px; }
QScrollBar::handle:hover { background:%(dim)s; }
QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; background:none; }
QScrollBar::add-page, QScrollBar::sub-page { background:none; }

QComboBox { background:%(raised)s; color:%(text)s; border:1px solid %(border)s;
            border-radius:6px; padding:4px 10px; min-height:18px; }
QComboBox:hover { background:%(hover)s; }
QComboBox QAbstractItemView { background:%(panel)s; color:%(text)s;
            border:1px solid %(border)s; selection-background-color:%(accent_soft)s;
            selection-color:%(text)s; outline:0; }

QListWidget#pages, QListWidget#layers { background:%(panel)s; border:1px solid %(border)s;
            border-radius:8px; outline:0; color:%(text)s; }
QListWidget#pages::item { border-radius:6px; padding:4px; margin:2px; }
QListWidget#layers::item { border-radius:5px; padding:3px 2px; margin:1px 2px; }
QListWidget#pages::item:hover, QListWidget#layers::item:hover { background:%(hover)s; }
QListWidget#pages::item:selected, QListWidget#layers::item:selected {
            background:%(accent_soft)s; color:%(text)s; }
QLabel[role="empty"] { color:%(dim)s; font-size:12px; padding:6px; }

QSplitter::handle { background:transparent; }
QSplitter::handle:horizontal { width:7px; }
QSplitter::handle:hover { background:%(border)s; }

QLabel[role="section"] { color:%(dim)s; font-size:11px; font-weight:700;
            letter-spacing:1px; padding:4px 2px 2px 2px; }
QLabel[role="hint-title"] { color:%(text)s; font-size:22px; font-weight:600; }
QLabel[role="hint"] { color:%(dim)s; font-size:13px; }
QWidget#toolbar { background:%(panel)s; border-bottom:1px solid %(border)s; }
QWidget#hint { background:%(canvas)s; }
""" % THEMES[nombre]


def apply_theme(nombre: str):
    global _theme
    _theme = nombre if nombre in THEMES else "dark"
    app = QApplication.instance()
    if app.style().objectName().lower() != "fusion":
        app.setStyle("Fusion")             # mismo aspecto en todos los sistemas
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark if _theme == "dark"
                                    else Qt.ColorScheme.Light)
    app.setPalette(fusion_palette(_theme))
    app.setStyleSheet(build_qss(_theme))


# --------------------------------------------------------------------------- #
#  Iconos dibujados en codigo (los de DriloBoard, y alguno nuevo)
# --------------------------------------------------------------------------- #
def swatch_icon(color: str, size: int = 18) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(QPen(QColor(128, 128, 128), 1))
    p.setBrush(QColor(color))
    p.drawRoundedRect(1, 1, size - 3, size - 3, 3, 3)
    p.end()
    return QIcon(pm)


def tool_icon(kind: str, size: int = 20) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    tinta = QColor(theme_color("ink"))
    lapiz = QPen(tinta, 1.8)
    lapiz.setCapStyle(Qt.PenCapStyle.RoundCap)
    lapiz.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(lapiz)
    p.setBrush(Qt.BrushStyle.NoBrush)
    m, M = 3.5, size - 3.5
    c = size / 2

    if kind == "move":
        p.drawLine(QPointF(c, m), QPointF(c, M))
        p.drawLine(QPointF(m, c), QPointF(M, c))
        p.drawPolyline([QPointF(c - 2.5, m + 2.5), QPointF(c, m), QPointF(c + 2.5, m + 2.5)])
        p.drawPolyline([QPointF(c - 2.5, M - 2.5), QPointF(c, M), QPointF(c + 2.5, M - 2.5)])
    elif kind == "pencil":
        p.drawLine(QPointF(m, M), QPointF(m + 3, M - 3))
        p.drawLine(QPointF(m + 3, M - 3), QPointF(M - 2, m + 2))
        p.drawLine(QPointF(m, M), QPointF(m + 1.2, M - 4.2))
    elif kind == "marker":
        grueso = QPen(QColor(252, 209, 22, 190), 6)
        grueso.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(grueso)
        p.drawLine(QPointF(m, M - 3), QPointF(M, m + 3))
        p.setPen(lapiz)
        p.drawLine(QPointF(m, M), QPointF(M, M))
    elif kind == "line":
        p.drawLine(QPointF(m, M), QPointF(M, m))
    elif kind == "arrow":
        p.drawLine(QPointF(m, M), QPointF(M - 1, m + 1))
        p.drawPolyline([QPointF(M - 6, m + 1), QPointF(M - 1, m + 1), QPointF(M - 1, m + 6)])
    elif kind == "rect":
        p.drawRect(QRectF(m, m + 1.5, M - m, M - m - 3))
    elif kind == "ellipse":
        p.drawEllipse(QRectF(m, m + 1.5, M - m, M - m - 3))
    elif kind == "text":
        p.drawLine(QPointF(m + 1, m + 1), QPointF(M - 1, m + 1))
        p.drawLine(QPointF(c, m + 1), QPointF(c, M))
        p.drawLine(QPointF(c - 3, M), QPointF(c + 3, M))
    elif kind == "eraser":
        p.drawPolygon([QPointF(m, M - 2), QPointF(m + 5, m + 1),
                       QPointF(M, m + 6), QPointF(M - 5, M - 2)])
        p.drawLine(QPointF(m + 2.5, M - 2), QPointF(M - 5, M - 2))
    elif kind == "add":
        p.drawRoundedRect(QRectF(m, m, M - m, M - m), 2.5, 2.5)
        p.drawLine(QPointF(c, m + 4), QPointF(c, M - 4))
        p.drawLine(QPointF(m + 4, c), QPointF(M - 4, c))
    elif kind == "trash":
        p.drawLine(QPointF(m, m + 3), QPointF(M, m + 3))
        p.drawPolyline([QPointF(c - 2, m + 3), QPointF(c - 2, m + 0.5),
                        QPointF(c + 2, m + 0.5), QPointF(c + 2, m + 3)])
        p.drawPolyline([QPointF(m + 2, m + 3), QPointF(m + 3, M), QPointF(M - 3, M),
                        QPointF(M - 2, m + 3)])
        p.drawLine(QPointF(c, m + 6), QPointF(c, M - 3))
    elif kind in ("undo", "redo"):
        sgn = -1 if kind == "redo" else 1
        cx = lambda x: c + sgn * x
        p.drawArc(QRectF(m + 1, m + 2, M - m - 2, M - m - 2),
                  (30 if kind == "undo" else 150) * 16, (200 if kind == "undo" else -200) * 16)
        p.drawPolyline([QPointF(cx(-7), m + 2), QPointF(cx(-7), m + 7), QPointF(cx(-2), m + 7)])
    elif kind == "clear":
        p.drawRoundedRect(QRectF(m, m, M - m, M - m), 2.5, 2.5)
        p.drawLine(QPointF(m + 4, m + 4), QPointF(M - 4, M - 4))
        p.drawLine(QPointF(M - 4, m + 4), QPointF(m + 4, M - 4))
    elif kind == "fit":
        p.drawRect(QRectF(m, m + 1, M - m, M - m - 2))
        p.drawLine(QPointF(m + 3, c), QPointF(M - 3, c))
        p.drawLine(QPointF(c, m + 4), QPointF(c, M - 4))
    elif kind == "pdf":
        p.drawPolyline([QPointF(M - 5, m), QPointF(m + 1, m), QPointF(m + 1, M),
                        QPointF(M - 1, M), QPointF(M - 1, m + 4), QPointF(M - 5, m),
                        QPointF(M - 5, m + 4), QPointF(M - 1, m + 4)])
        p.drawLine(QPointF(m + 4, c), QPointF(M - 4, c))
        p.drawLine(QPointF(m + 4, c + 3.5), QPointF(M - 4, c + 3.5))
    elif kind == "folder":
        p.drawPolyline([QPointF(m, M - 1), QPointF(m, m + 2), QPointF(m + 5, m + 2),
                        QPointF(m + 7, m + 4.5), QPointF(M, m + 4.5), QPointF(M, M - 1),
                        QPointF(m, M - 1)])
    elif kind == "save":
        p.drawRoundedRect(QRectF(m, m, M - m, M - m), 2, 2)
        p.drawRect(QRectF(m + 3, m, M - m - 6, 4.5))
        p.drawRect(QRectF(m + 3, M - 6.5, M - m - 6, 6.5))
    elif kind == "select":                      # el puntero del raton
        p.setBrush(tinta)
        p.drawPolygon([QPointF(m + 2, m), QPointF(m + 2, M - 2), QPointF(m + 6, M - 6),
                       QPointF(m + 9, M), QPointF(m + 11, M - 1), QPointF(m + 8, M - 7),
                       QPointF(M - 2, M - 7)])
    elif kind in ("raise", "lower"):            # una capa sube o baja
        sube = kind == "raise"
        y0 = m + 2 if sube else M - 2
        p.drawPolyline([QPointF(c - 4.5, y0 + (4.5 if sube else -4.5)), QPointF(c, y0),
                        QPointF(c + 4.5, y0 + (4.5 if sube else -4.5))])
        p.drawLine(QPointF(c, y0), QPointF(c, y0 + (8 if sube else -8)))
        for i in range(2):
            y = (M - 3 - i * 3.5) if sube else (m + 3 + i * 3.5)
            p.drawLine(QPointF(m + 1, y), QPointF(M - 1, y))
    elif kind in ("eye", "eye_off"):
        ojo = QPainterPath()
        ojo.moveTo(m - 0.5, c)
        ojo.quadTo(c, m - 1, M + 0.5, c)
        ojo.quadTo(c, M + 1, m - 0.5, c)
        if kind == "eye_off":
            apagado = QColor(tinta)
            apagado.setAlpha(110)
            p.setPen(QPen(apagado, 1.6))
            p.drawPath(ojo)
            p.setPen(lapiz)
            p.drawLine(QPointF(m + 1, M - 1), QPointF(M - 1, m + 1))
        else:
            p.drawPath(ojo)
            p.setBrush(tinta)
            p.drawEllipse(QPointF(c, c), 2.4, 2.4)
    elif kind == "paste":                       # portapapeles
        p.drawRoundedRect(QRectF(m + 1, m + 2, M - m - 2, M - m - 2), 2, 2)
        p.setBrush(tinta)
        p.drawRoundedRect(QRectF(c - 3, m, 6, 3.5), 1, 1)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(m + 4, c + 1), QPointF(M - 4, c + 1))
        p.drawLine(QPointF(m + 4, c + 4.5), QPointF(M - 6, c + 4.5))
    elif kind == "sun":
        o = QPointF(c, c)
        p.drawEllipse(o, size * 0.19, size * 0.19)
        for i in range(8):
            a = i * math.pi / 4
            p.drawLine(QPointF(o.x() + math.cos(a) * size * 0.32, o.y() + math.sin(a) * size * 0.32),
                       QPointF(o.x() + math.cos(a) * size * 0.44, o.y() + math.sin(a) * size * 0.44))
    elif kind == "moon":
        luna = QPainterPath()
        luna.addEllipse(QRectF(m, m, M - m, M - m))
        mordisco = QPainterPath()
        mordisco.addEllipse(QRectF(m + size * 0.28, m - size * 0.12, M - m, M - m))
        p.setBrush(tinta)
        p.drawPath(luna.subtracted(mordisco))
    p.end()
    return QIcon(pm)


def app_pixmap(size: int = 256) -> QPixmap:
    """El icono: una hoja con una flecha roja y un trazo de rotulador encima."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    u = size / 32.0
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#1d4e6f"))
    p.drawRoundedRect(QRectF(u, u, 30 * u, 30 * u), 6 * u, 6 * u)
    hoja = QPainterPath()                               # hoja con la esquina doblada
    hoja.moveTo(8 * u, 5 * u)
    hoja.lineTo(19 * u, 5 * u)
    hoja.lineTo(25 * u, 11 * u)
    hoja.lineTo(25 * u, 27 * u)
    hoja.lineTo(8 * u, 27 * u)
    hoja.closeSubpath()
    p.setBrush(QColor("#ffffff"))
    p.drawPath(hoja)
    p.setBrush(QColor("#c9d6df"))
    pliegue = QPainterPath()
    pliegue.moveTo(19 * u, 5 * u)
    pliegue.lineTo(19 * u, 11 * u)
    pliegue.lineTo(25 * u, 11 * u)
    pliegue.closeSubpath()
    p.drawPath(pliegue)
    p.setBrush(QColor("#8fb3c9"))                       # la "foto" de la hoja
    p.drawRoundedRect(QRectF(10.5 * u, 13 * u, 12 * u, 9 * u), 1 * u, 1 * u)
    rotulador = QPen(QColor(252, 209, 22, 210), 3 * u)
    rotulador.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(rotulador)
    p.drawLine(QPointF(11 * u, 24.5 * u), QPointF(21 * u, 24.5 * u))
    flecha = QPen(QColor("#e81123"), 2 * u)
    flecha.setCapStyle(Qt.PenCapStyle.RoundCap)
    flecha.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(flecha)
    p.drawLine(QPointF(27 * u, 27 * u), QPointF(18.5 * u, 18.5 * u))
    p.drawPolyline([QPointF(18.5 * u, 23 * u), QPointF(18.5 * u, 18.5 * u),
                    QPointF(23 * u, 18.5 * u)])
    p.end()
    return pm


def app_icon() -> QIcon:
    ico = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256, 512):
        ico.addPixmap(app_pixmap(s))
    return ico


# --------------------------------------------------------------------------- #
#  Dibujos: el mismo formato que DriloBoard (tipo, puntos, color, grosor, alpha)
#  Los puntos van en pixeles de la imagen original, ya girada segun su EXIF.
# --------------------------------------------------------------------------- #
DRAW_TOOLS = ("trazo", "rotulador", "linea", "flecha", "rect", "elipse", "texto")

# Los 8 del arco iris mas blanco y negro
DRAW_COLORS = [("Red", "#e81123"), ("Orange", "#f7630c"), ("Yellow", "#fcd116"),
               ("Green", "#16a34a"), ("Cyan", "#00b7c3"), ("Blue", "#0078d4"),
               ("Indigo", "#4b0082"), ("Violet", "#8e44ad"),
               ("White", "#ffffff"), ("Black", "#000000")]

# (herramienta, icono, nombre, atajo, explicacion)
TOOLS = [(None, "select", "Select and move", "V",
          "Click a drawing to select it and drag it to move it; double-click a text to edit "
          "it. Dragging the background moves the page, the wheel zooms"),
         ("trazo", "pencil", "Pen", "P", "Freehand stroke"),
         ("rotulador", "marker", "Highlighter", "H", "Thick, see-through stroke"),
         ("linea", "line", "Line", "L", "Straight line (Shift: snap to 45°)"),
         ("flecha", "arrow", "Arrow", "A", "Arrow to point at something (Shift: snap to 45°)"),
         ("rect", "rect", "Rectangle", "R", "Rectangle (Shift: square)"),
         ("elipse", "ellipse", "Ellipse", "O", "Ellipse (Shift: circle)"),
         ("texto", "text", "Text", "T", "Click and type"),
         ("goma", "eraser", "Eraser", "E", "Remove the drawing you click on")]


LAYER_NAMES = {"trazo": "Pen", "rotulador": "Highlighter", "linea": "Line",
               "flecha": "Arrow", "rect": "Rectangle", "elipse": "Ellipse", "texto": "Text"}
LAYER_ICONS = {"trazo": "pencil", "rotulador": "marker", "linea": "line", "flecha": "arrow",
               "rect": "rect", "elipse": "ellipse", "texto": "text"}


def new_shape_id() -> str:
    return uuid.uuid4().hex[:12]


def with_ids(formas: list) -> list:
    """Cada dibujo lleva un id: asi la seleccion y las capas lo siguen aunque
    cambie de sitio en la lista. Los proyectos viejos se completan al abrir."""
    return [f if f.get("id") else dict(f, id=new_shape_id()) for f in formas]


def shape_label(forma: dict) -> str:
    nombre = LAYER_NAMES.get(forma.get("tipo"), "Drawing")
    if forma.get("tipo") == "texto":
        linea = (forma.get("texto") or "").split("\n")[0].strip()
        if len(linea) > 22:
            linea = linea[:21] + "…"
        return "%s “%s”" % (nombre, linea)
    return nombre


def translate_shape(forma: dict, dx: float, dy: float) -> dict:
    """Una copia movida (nunca se toca la original: el deshacer la guarda)."""
    return dict(forma, puntos=[[round(x + dx, 2), round(y + dy, 2)]
                               for x, y in forma.get("puntos", [])])


def shape_path(forma: dict) -> QPainterPath:
    """El contorno de una forma, en las coordenadas en que vengan sus puntos."""
    pts = [QPointF(x, y) for x, y in forma.get("puntos", [])]
    path = QPainterPath()
    if not pts:
        return path
    tipo = forma.get("tipo")
    if tipo in ("trazo", "rotulador"):
        path.moveTo(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        if len(pts) == 1:                    # un simple clic: un punto
            path.lineTo(pts[0].x() + 0.01, pts[0].y())
    elif tipo == "linea":
        path.moveTo(pts[0])
        path.lineTo(pts[-1])
    elif tipo == "rect":
        path.addRect(QRectF(pts[0], pts[-1]).normalized())
    elif tipo == "elipse":
        path.addEllipse(QRectF(pts[0], pts[-1]).normalized())
    elif tipo == "flecha":
        a, b = pts[0], pts[-1]
        path.moveTo(a)
        path.lineTo(b)
        dx, dy = b.x() - a.x(), b.y() - a.y()
        if math.hypot(dx, dy) > 0.5:
            cabeza = max(6.0, forma.get("grosor", 4) * 3.5)
            ang = math.atan2(dy, dx)
            for giro in (2.6, -2.6):
                path.moveTo(b)
                path.lineTo(b.x() + cabeza * math.cos(ang + giro),
                            b.y() + cabeza * math.sin(ang + giro))
    return path


def text_font(forma: dict) -> QFont:
    f = QFont()
    f.setPixelSize(max(4, int(forma.get("grosor", 4) * 5)))
    f.setBold(True)
    return f


def paint_shape(p: QPainter, forma: dict):
    color = QColor(forma.get("color", "#e81123"))
    color.setAlpha(int(forma.get("alpha", 255)))
    if forma.get("tipo") == "texto":
        p.setFont(text_font(forma))
        p.setPen(color)
        x, y = (forma.get("puntos") or [[0, 0]])[0]
        alto = p.fontMetrics().lineSpacing()
        for i, linea in enumerate(forma.get("texto", "").split("\n")):
            p.drawText(QPointF(x, y + i * alto), linea)
        return
    pen = QPen(color, max(0.1, float(forma.get("grosor", 4))))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(shape_path(forma))


def paint_shapes(p: QPainter, formas: list):
    """Pinta los dibujos visibles, de abajo arriba (el ultimo queda encima)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    for forma in formas:
        if not forma.get("oculto"):
            paint_shape(p, forma)
    p.restore()


def text_rect(forma: dict) -> QRectF:
    x, y = (forma.get("puntos") or [[0, 0]])[0]
    fm = QFontMetricsF(text_font(forma))
    lineas = forma.get("texto", "").split("\n")
    ancho = max((fm.horizontalAdvance(l) for l in lineas), default=0)
    return QRectF(x, y - fm.ascent(), ancho, fm.lineSpacing() * len(lineas))


def shape_bounds(forma: dict) -> QRectF:
    """La caja que ocupa el dibujo, con el grosor del trazo."""
    if forma.get("tipo") == "texto":
        return text_rect(forma)
    g = float(forma.get("grosor", 4)) / 2
    return shape_path(forma).boundingRect().adjusted(-g, -g, g, g)


def shape_hit(forma: dict, punto: QPointF, tolerancia: float, interior: bool = False) -> bool:
    """Si el punto (en coordenadas de la imagen) cae sobre el dibujo.

    Con interior=True vale tambien el hueco de rectangulos y elipses: es lo
    comodo para seleccionarlos, pero la goma solo borra si tocas el trazo."""
    if forma.get("tipo") == "texto":
        zona = text_rect(forma)
        return zona.adjusted(-tolerancia, -tolerancia, tolerancia, tolerancia).contains(punto)
    if interior and forma.get("tipo") in ("rect", "elipse") and shape_path(forma).contains(punto):
        return True
    stroker = QPainterPathStroker()
    stroker.setWidth(float(forma.get("grosor", 4)) + 2 * tolerancia)
    return stroker.createStroke(shape_path(forma)).contains(punto)


def shape_at(formas: list, punto: QPointF, tolerancia: float, interior: bool = False):
    """El indice del dibujo visible de mas arriba bajo el punto, o None."""
    for i in range(len(formas) - 1, -1, -1):
        if not formas[i].get("oculto") and shape_hit(formas[i], punto, tolerancia, interior):
            return i
    return None


EYE_WIDTH = 24                      # el ojo de cada capa: un clic ahi la oculta o muestra


def layer_icon(forma: dict) -> QIcon:
    """El ojo (visible u oculta), la herramienta con que se hizo y su color."""
    dpr = 2
    pm = QPixmap((EYE_WIDTH + 38) * dpr, 20 * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.drawPixmap(0, 0, tool_icon("eye_off" if forma.get("oculto") else "eye").pixmap(20, 20))
    p.drawPixmap(EYE_WIDTH, 0,
                 tool_icon(LAYER_ICONS.get(forma.get("tipo"), "pencil")).pixmap(20, 20))
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(QPen(QColor(128, 128, 128), 1))
    p.setBrush(QColor(forma.get("color", "#e81123")))
    p.drawRoundedRect(QRectF(EYE_WIDTH + 23, 4, 12, 12), 3, 3)
    p.end()
    return QIcon(pm)


# --------------------------------------------------------------------------- #
#  Imagenes
# --------------------------------------------------------------------------- #
def _rotated(r: QImageReader) -> bool:
    """Si el EXIF pide girar 90 grados (y el ancho y el alto se cambian)."""
    return bool(r.transformation() & QImageIOHandler.Transformation.TransformationRotate90)


def read_image(path: str, max_side: int | None = None) -> QImage:
    """Lee la imagen ya girada segun su EXIF, reducida si pasa de max_side."""
    r = QImageReader(path)
    r.setAutoTransform(True)
    size = r.size()                         # en la orientacion del archivo
    if size.isValid():
        w, h = size.width(), size.height()
        k = 1.0
        if max_side and max(w, h) > max_side:
            k = max_side / max(w, h)
        if w * h * k * k > MAX_PIXELS:
            k = math.sqrt(MAX_PIXELS / (w * h))
        if k < 1.0:
            r.setScaledSize(QSize(max(1, round(w * k)), max(1, round(h * k))))
    return r.read()


def image_size(path: str) -> tuple | None:
    """Tamano de la imagen tal y como se ve (con el giro del EXIF), sin leerla."""
    r = QImageReader(path)
    r.setAutoTransform(True)
    size = r.size()
    if not size.isValid():
        img = r.read()
        return (img.width(), img.height()) if not img.isNull() else None
    if _rotated(r):
        size = size.transposed()
    return size.width(), size.height()


def scan_paths(rutas: list, exts: set) -> list:
    """Las imagenes de una lista de archivos y carpetas, en orden natural."""
    import re

    def natural(s):
        return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]

    salida = []
    for ruta in rutas:
        p = Path(ruta)
        if p.is_dir():
            dentro = []
            for raiz, dirs, archivos in os.walk(p):
                dirs[:] = sorted((d for d in dirs if not d.startswith(".")), key=natural)
                for a in archivos:
                    if not a.startswith(".") and Path(a).suffix.lower() in exts:
                        dentro.append(os.path.join(raiz, a))
            salida.extend(sorted(dentro, key=natural))
        elif p.is_file() and p.suffix.lower() in exts:
            salida.append(str(p))
    return salida


class ThumbSignals(QObject):
    done = Signal(str, QImage, object)          # ruta, miniatura, tamano (w, h)


class ThumbTask(QRunnable):
    def __init__(self, path: str):
        super().__init__()
        self.path = path
        self.signals = ThumbSignals()

    def run(self):
        size = image_size(self.path)
        img = read_image(self.path, THUMB_SIZE * 2) if size else QImage()
        if not img.isNull():
            img = img.scaled(THUMB_SIZE, THUMB_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        try:
            self.signals.done.emit(self.path, img, size)
        except RuntimeError:                     # la ventana ya se cerro
            pass


def missing_image(w: int = 400, h: int = 300) -> QImage:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#5b5e66"))
    p = QPainter(img)
    p.setPen(QColor("white"))
    f = QFont()
    f.setPixelSize(max(12, h // 10))
    p.setFont(f)
    p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, "Image not found")
    p.end()
    return img


# --------------------------------------------------------------------------- #
#  Exportar a PDF
# --------------------------------------------------------------------------- #
PAGE_FORMATS = [("fit", "Same shape as each image"),
                ("a4", "A4 (portrait or landscape to suit)"),
                ("letter", "US Letter (portrait or landscape to suit)")]
QUALITIES = [(None, "Original resolution"), (3000, "High (3000 px)"),
             (1800, "Medium (1800 px) – smaller file"), (1200, "Small (1200 px)")]


def export_pdf(pages: list, destino: str, formato: str = "fit", max_side: int | None = 3000,
               margen_mm: float = 0.0, pie: bool = False, progreso=None) -> int:
    """Escribe el PDF: una pagina por imagen, con sus dibujos encima como vectores.

    Devuelve el numero de paginas. `progreso(i)` se llama antes de cada pagina y
    si devuelve False se cancela (y no se deja un PDF a medias)."""
    if not pages:
        return 0
    tmp = destino + ".part"
    writer = QPdfWriter(tmp)
    writer.setCreator("%s %s, by %s" % (APP_NAME, VERSION, APP_AUTHOR))
    writer.setTitle(Path(destino).stem)
    writer.setResolution(300)
    dpi = 300.0
    p = None
    hechas = 0
    try:
        for i, page in enumerate(pages):
            if progreso is not None and progreso(i) is False:
                raise InterruptedError
            img = read_image(page["path"], max_side) if os.path.exists(page["path"]) else QImage()
            if img.isNull():
                img = missing_image()
            ow, oh = page.get("size") or (img.width(), img.height())
            apaisada = ow > oh
            if formato == "fit":
                # 25 cm el lado mayor: se ve bien en pantalla e imprime decente
                lado = 250.0
                k = lado / max(ow, oh)
                tam = QPageSize(QSizeF(ow * k + 2 * margen_mm,
                                       oh * k + 2 * margen_mm + (8 if pie else 0)),
                                QPageSize.Unit.Millimeter, "", QPageSize.SizeMatchPolicy.ExactMatch)
                orient = QPageLayout.Orientation.Portrait
            else:
                tam = QPageSize(QPageSize.PageSizeId.A4 if formato == "a4"
                                else QPageSize.PageSizeId.Letter)
                orient = (QPageLayout.Orientation.Landscape if apaisada
                          else QPageLayout.Orientation.Portrait)
            layout = QPageLayout(tam, orient, QMarginsF(0, 0, 0, 0))
            if p is None:
                writer.setPageLayout(layout)
                p = QPainter(writer)
                if not p.isActive():
                    raise OSError("Cannot write %s" % destino)
            else:
                writer.setPageLayout(layout)
                writer.newPage()
            pagina = layout.fullRectPixels(int(dpi))
            m = margen_mm / 25.4 * dpi
            area = QRectF(pagina).adjusted(m, m, -m, -m)
            if pie:
                area.adjust(0, 0, 0, -8 / 25.4 * dpi)
            k = min(area.width() / ow, area.height() / oh)
            destino_rect = QRectF(0, 0, ow * k, oh * k)
            destino_rect.moveCenter(area.center())
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.drawImage(destino_rect, img)
            p.save()
            p.setClipRect(destino_rect)
            p.translate(destino_rect.topLeft())
            p.scale(k, k)
            paint_shapes(p, page.get("draw") or [])
            p.restore()
            if pie:
                f = QFont()
                f.setPixelSize(int(3.2 / 25.4 * dpi))
                p.setFont(f)
                p.setPen(QColor("#555555"))
                texto = "%d · %s" % (i + 1, os.path.basename(page["path"]))
                p.drawText(QRectF(area.left(), destino_rect.bottom(), area.width(),
                                  8 / 25.4 * dpi), Qt.AlignmentFlag.AlignCenter, texto)
            hechas += 1
    except InterruptedError:
        if p is not None:
            p.end()
        p = None
        del writer
        _remove_quietly(tmp)
        return 0
    except Exception:
        if p is not None:
            p.end()
        p = None
        del writer
        _remove_quietly(tmp)
        raise
    finally:
        if p is not None:
            p.end()
    del writer
    try:
        # en Windows falla si el PDF anterior sigue abierto en un visor
        os.replace(tmp, destino)
    except OSError:
        _remove_quietly(tmp)
        raise
    return hechas


def _remove_quietly(path: str):
    try:
        os.remove(path)
    except OSError:
        pass


class ExportDialog(QDialog):
    def __init__(self, parent, n: int, ajustes: QSettings):
        super().__init__(parent)
        self.setWindowTitle("Export PDF")
        self.ajustes = ajustes
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("%d page%s, in the order of the strip." % (n, "" if n == 1 else "s")))
        form = QFormLayout()
        self.cmb_formato = QComboBox()
        for clave, nombre in PAGE_FORMATS:
            self.cmb_formato.addItem(nombre, clave)
        self.cmb_calidad = QComboBox()
        for clave, nombre in QUALITIES:
            self.cmb_calidad.addItem(nombre, clave)
        self.cmb_margen = QComboBox()
        for mm, nombre in ((0, "None"), (5, "Small (5 mm)"), (10, "Medium (10 mm)"),
                           (20, "Large (20 mm)")):
            self.cmb_margen.addItem(nombre, mm)
        self.chk_pie = QCheckBox("Page number and file name under each image")
        form.addRow("Page size", self.cmb_formato)
        form.addRow("Image quality", self.cmb_calidad)
        form.addRow("Margin", self.cmb_margen)
        lay.addLayout(form)
        lay.addWidget(self.chk_pie)
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        ok = botones.addButton("Export…", QDialogButtonBox.ButtonRole.AcceptRole)
        ok.setProperty("primary", True)
        ok.setDefault(True)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)
        for cmb, clave, defecto in ((self.cmb_formato, "pdf/format", 0),
                                    (self.cmb_calidad, "pdf/quality", 1),
                                    (self.cmb_margen, "pdf/margin", 0)):
            cmb.setCurrentIndex(int(ajustes.value(clave, defecto)))
        self.chk_pie.setChecked(ajustes.value("pdf/caption", "false") == "true")

    def options(self) -> dict:
        self.ajustes.setValue("pdf/format", self.cmb_formato.currentIndex())
        self.ajustes.setValue("pdf/quality", self.cmb_calidad.currentIndex())
        self.ajustes.setValue("pdf/margin", self.cmb_margen.currentIndex())
        self.ajustes.setValue("pdf/caption", "true" if self.chk_pie.isChecked() else "false")
        return {"formato": self.cmb_formato.currentData(),
                "max_side": self.cmb_calidad.currentData(),
                "margen_mm": float(self.cmb_margen.currentData()),
                "pie": self.chk_pie.isChecked()}


# --------------------------------------------------------------------------- #
#  Lienzo
# --------------------------------------------------------------------------- #
class AnnotationItem(QGraphicsItem):
    """Pinta los dibujos de la pagina, recortados al borde de la imagen."""

    def __init__(self):
        super().__init__()
        self.rect = QRectF()
        self.formas: list = []
        self.selected: str | None = None        # id del dibujo seleccionado

    def set_page(self, rect: QRectF, formas: list):
        self.prepareGeometryChange()
        self.rect = QRectF(rect)
        self.formas = formas
        self.update()

    def boundingRect(self):
        return self.rect

    def paint(self, painter, _option, _widget=None):
        painter.save()
        painter.setClipRect(self.rect)
        paint_shapes(painter, self.formas)
        painter.restore()
        sel = next((f for f in self.formas if f.get("id") == self.selected
                    and not f.get("oculto")), None)
        if sel is not None:
            # marco discontinuo de un pixel de pantalla, sea cual sea el zoom
            caja = shape_bounds(sel)
            for color, estilo in ((QColor(0, 0, 0, 150), Qt.PenStyle.SolidLine),
                                  (QColor(theme_color("accent")), Qt.PenStyle.DashLine)):
                pen = QPen(color, 1.5, estilo)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(caja)


class Canvas(QGraphicsView):
    """Muestra la pagina actual y recoge los trazos de la herramienta elegida.

    La escena va en pixeles de la imagen original: lo que se dibuja ya sale en
    esas coordenadas, aunque la imagen en pantalla vaya reducida."""
    drawn = Signal(dict)
    erase_at = Signal(QPointF, float)           # punto y tolerancia, en pixeles de imagen
    zoom_changed = Signal(float)
    move_by = Signal(float, float)              # desplazamiento desde que se pincho
    move_done = Signal()
    edit_at = Signal(QPointF, float)            # doble clic con la flecha
    delete_key = Signal()
    escape_key = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing
                            | QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        # sin barras: la pagina se mueve arrastrando; con ellas, al encajar
        # aparecia una que no hacia falta
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAcceptDrops(False)              # las imagenes las recoge la ventana
        self.viewport().setAcceptDrops(False)
        self.pix = QGraphicsPixmapItem()
        self.pix.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.scene().addItem(self.pix)
        self.notes = AnnotationItem()
        self.notes.setZValue(1)
        self.scene().addItem(self.notes)
        self.preview = QGraphicsPathItem()
        self.preview.setZValue(10)
        self.scene().addItem(self.preview)
        self.tool = None
        self.color = QColor(DRAW_COLORS[0][1])
        self.width = 6                          # en milesimas del lado mayor de la imagen
        self.img_size = (0, 0)
        self._puntos: list = []
        self._pan_from = None
        self._move_from = None
        self._fitted = True
        # la ventana dice que hay bajo el raton: picker selecciona y hover solo mira
        self.picker = None                      # fn(punto, tolerancia) -> bool
        self.hover = None                       # fn(punto, tolerancia) -> bool
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.set_tool(None)

    # -- pagina ------------------------------------------------------------ #
    def show_page(self, img: QImage, size: tuple, formas: list):
        w, h = size
        self.img_size = (w, h)
        self.pix.setPixmap(QPixmap.fromImage(img))
        self.pix.setScale(w / img.width() if img.width() else 1.0)
        rect = QRectF(0, 0, w, h)
        self.notes.set_page(rect, formas)
        margen = max(w, h) * 0.04
        self.scene().setSceneRect(rect.adjusted(-margen, -margen, margen, margen))
        self._cancel_stroke()
        self.fit()

    def refresh_notes(self, formas: list):
        self.notes.formas = formas
        self.notes.update()

    def unit(self) -> float:
        """Pixeles de imagen por cada punto del deslizador de grosor."""
        return max(self.img_size) / 1000.0 if max(self.img_size) else 1.0

    # -- zoom -------------------------------------------------------------- #
    def zoom(self) -> float:
        return self.transform().m11()

    def fit(self):
        if not self.img_size[0]:
            return
        self.resetTransform()
        self.fitInView(QRectF(0, 0, *self.img_size).adjusted(-10, -10, 10, 10),
                       Qt.AspectRatioMode.KeepAspectRatio)
        self._fitted = True
        self.zoom_changed.emit(self.zoom())

    def zoom_by(self, f: float):
        z = self.zoom()
        f = max(0.02 / z, min(f, 40 / z))       # entre el 2 % y el 4000 %
        self.scale(f, f)
        self._fitted = False
        self.zoom_changed.emit(self.zoom())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fitted:
            self.fit()

    def wheelEvent(self, e):
        d = e.angleDelta().y() or e.angleDelta().x()
        if d:
            self.zoom_by(1.0015 ** d)

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor(theme_color("canvas")))

    # -- herramientas ------------------------------------------------------ #
    def tolerance(self) -> float:
        """8 pixeles de pantalla, en pixeles de imagen."""
        return 8 / max(self.zoom(), 1e-6)

    def set_tool(self, tool):
        self.tool = tool
        self._cancel_stroke()
        self.setDragMode(QGraphicsView.DragMode.NoDrag)   # el arrastre lo llevo yo
        if tool is None:
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor if tool == "texto"
                                      else Qt.CursorShape.CrossCursor)

    def _pan(self, pos):
        d = pos - self._pan_from
        self._pan_from = pos
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))

    def _cancel_stroke(self):
        self._puntos = []
        self.preview.setPath(QPainterPath())

    def _forma(self) -> dict:
        rotulador = self.tool == "rotulador"
        grosor = self.width * self.unit() * (4 if rotulador else 1)
        return {"id": new_shape_id(), "tipo": self.tool,
                "puntos": [[round(p.x(), 2), round(p.y(), 2)] for p in self._puntos],
                "color": self.color.name(), "grosor": round(grosor, 2),
                "alpha": 90 if rotulador else 255}

    def _pintar_preview(self):
        forma = self._forma()
        c = QColor(self.color)
        c.setAlpha(forma["alpha"])
        pen = QPen(c, max(0.5, forma["grosor"]))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.preview.setPen(pen)
        self.preview.setPath(shape_path(forma))

    @staticmethod
    def _snap(a: QPointF, b: QPointF, tipo: str) -> QPointF:
        """Con Mayusculas: lineas a 45 grados, cuadrados y circulos."""
        dx, dy = b.x() - a.x(), b.y() - a.y()
        if tipo in ("rect", "elipse"):
            lado = max(abs(dx), abs(dy))
            return QPointF(a.x() + math.copysign(lado, dx or 1),
                           a.y() + math.copysign(lado, dy or 1))
        ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
        largo = math.hypot(dx, dy)
        return QPointF(a.x() + largo * math.cos(ang), a.y() + largo * math.sin(ang))

    def mousePressEvent(self, e):
        self.setFocus()
        if e.button() == Qt.MouseButton.MiddleButton:
            # el boton central siempre arrastra la pagina, con cualquier herramienta
            self._pan_from = e.position()
            return
        if not self.img_size[0] or e.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(e)
            return
        punto = self.mapToScene(e.position().toPoint())
        if self.tool is None:
            if self.picker is not None and self.picker(punto, self.tolerance()):
                self._move_from = punto            # pinchado un dibujo: se mueve
                self.viewport().setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self._pan_from = e.position()      # en vacio: se mueve la pagina
                self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if self.tool == "goma":
            self.erase_at.emit(punto, self.tolerance())
            return
        self._puntos = [punto]
        if self.tool == "texto":
            forma = self._forma()
            self._cancel_stroke()
            self.drawn.emit(forma)
            return
        self._pintar_preview()

    def mouseMoveEvent(self, e):
        if self._pan_from is not None:
            self._pan(e.position())
            return
        if self._move_from is not None:
            d = self.mapToScene(e.position().toPoint()) - self._move_from
            self.move_by.emit(d.x(), d.y())
            return
        if self.tool is None and self.hover is not None and self.img_size[0]:
            encima = self.hover(self.mapToScene(e.position().toPoint()), self.tolerance())
            self.viewport().setCursor(Qt.CursorShape.SizeAllCursor if encima
                                      else Qt.CursorShape.ArrowCursor)
        if self.tool in DRAW_TOOLS and self._puntos:
            p = self.mapToScene(e.position().toPoint())
            if self.tool in ("trazo", "rotulador"):
                self._puntos.append(p)
            else:
                if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    p = self._snap(self._puntos[0], p, self.tool)
                self._puntos = [self._puntos[0], p]
            self._pintar_preview()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._pan_from is not None and e.button() in (Qt.MouseButton.MiddleButton,
                                                         Qt.MouseButton.LeftButton):
            self._pan_from = None
            if self.tool is None:
                self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            return
        if self._move_from is not None and e.button() == Qt.MouseButton.LeftButton:
            self._move_from = None
            self.move_done.emit()
            return
        if self.tool in DRAW_TOOLS and self._puntos:
            forma = self._forma()
            self._cancel_stroke()
            if len(forma["puntos"]) > 1 or forma["tipo"] in ("trazo", "rotulador"):
                self.drawn.emit(forma)
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if self.tool is None and e.button() == Qt.MouseButton.LeftButton and self.img_size[0]:
            self.edit_at.emit(self.mapToScene(e.position().toPoint()), self.tolerance())
            return
        super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_key.emit()
            return
        if e.key() == Qt.Key.Key_Escape:
            self.escape_key.emit()
            return
        super().keyPressEvent(e)


ICON_BOX = 150                      # las miniaturas de la tira, dentro de este cuadrado


class PageDelegate(QStyledItemDelegate):
    """Miniatura arriba y nombre debajo, en una lista normal (que si reordena)."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.decorationPosition = QStyleOptionViewItem.Position.Top
        option.decorationAlignment = Qt.AlignmentFlag.AlignHCenter
        option.displayAlignment = Qt.AlignmentFlag.AlignHCenter
        option.decorationSize = QSize(ICON_BOX, ICON_BOX)

    def sizeHint(self, option, index):
        alto = option.fontMetrics.height()
        return QSize(ICON_BOX + 16, ICON_BOX + alto + 18)


class ArrowKeysList(QListWidget):
    """Con el foco en la lista, arriba y abajo se mueven por ella: no los roban
    los atajos de la ventana que pasan de pagina."""

    def event(self, e):
        if e.type() == QEvent.Type.ShortcutOverride and e.key() in (
                Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End):
            if not e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
                e.accept()
                return True
        return super().event(e)


class PageList(ArrowKeysList):
    """La tira de paginas: se reordena arrastrando y acepta imagenes de fuera."""
    files_dropped = Signal(list, int)           # rutas, fila donde insertarlas
    reordered = Signal()
    delete_pressed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pages")
        self.setItemDelegate(PageDelegate(self))
        self.setIconSize(QSize(ICON_BOX, ICON_BOX))
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setMinimumWidth(ICON_BOX + 40)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def _drop_row(self, pos) -> int:
        item = self.itemAt(pos)
        if item is None:
            return self.count()
        fila = self.row(item)
        r = self.visualItemRect(item)
        return fila + 1 if pos.y() > r.center().y() else fila

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            rutas = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            e.acceptProposedAction()
            self.files_dropped.emit(rutas, self._drop_row(e.position().toPoint()))
            return
        super().dropEvent(e)
        self.reordered.emit()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_pressed.emit()
            return
        super().keyPressEvent(e)


class LayerList(ArrowKeysList):
    """Las capas de la pagina: la de arriba de la lista es la que queda encima.

    La casilla oculta o muestra; arrastrar reordena; Supr borra."""
    reordered = Signal()
    delete_pressed = Signal()
    eye_clicked = Signal(str)                   # id del dibujo

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("layers")
        self.setIconSize(QSize(EYE_WIDTH + 38, 20))
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAcceptDrops(True)

    def mousePressEvent(self, e):
        item = self.itemAt(e.position().toPoint())
        if item is not None and e.button() == Qt.MouseButton.LeftButton:
            x = e.position().x() - self.visualItemRect(item).left()
            if x < EYE_WIDTH + 4:               # el ojo no selecciona ni arrastra
                self.eye_clicked.emit(item.data(SHAPE_ROLE))
                return
        super().mousePressEvent(e)

    def dropEvent(self, e):
        if e.source() is not self:              # imagenes de fuera: a la ventana
            e.ignore()
            return
        super().dropEvent(e)
        self.reordered.emit()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_pressed.emit()
            return
        super().keyPressEvent(e)


# --------------------------------------------------------------------------- #
#  Ventana principal
# --------------------------------------------------------------------------- #
HELP_TEXT = """<h3>DriloReview</h3>
<p><b>1. Add images</b>: drag them (or whole folders) onto the window, or paste them
with <b>%(paste)s</b> — a screenshot, an image copied from a web page, or files copied
in the Finder / Explorer. Each image is a page. Drop them on the page strip to put
them at a precise spot, and drag the pages there to reorder them.</p>
<p><b>2. Draw</b> with the tools at the top: pen, highlighter, line, arrow,
rectangle, ellipse and text. Hold <b>Shift</b> for 45° lines, squares and circles.
The eraser removes the whole drawing you click on.</p>
<p><b>3. Move what you drew</b>: with <b>Select and move</b> (V) click a drawing and
drag it. Double-click a text to change it; click a colour to recolour it.
The <b>Layers</b> panel lists every drawing of the page, the top one in front:
drag them to reorder, untick to hide (hidden layers stay out of the PDF).</p>
<p><b>4. Export PDF</b>: one page per image, in the order of the strip, with the
drawings as sharp vectors.</p>
<p>Your image files are never modified. <i>Save project</i> keeps the pages and the
drawings in a .driloreview file so you can carry on later; pasted images are copied
next to it.</p>
<table cellspacing="6">
<tr><td><b>V P H L A R O T E</b></td><td>tools (select, pen, highlighter, line, arrow, rectangle, ellipse, text, eraser)</td></tr>
<tr><td><b>Delete · Esc</b></td><td>delete the selected drawing · deselect</td></tr>
<tr><td><b>%(copy)s · %(paste)s · %(dup)s</b></td><td>copy · paste · duplicate a drawing</td></tr>
<tr><td><b>%(fwd)s · %(back)s</b></td><td>bring forward · send backward (also %(fwd2)s · %(back2)s; with Shift and [ ]: to the front / back)</td></tr>
<tr><td><b>← → / PgUp PgDn</b></td><td>previous / next page</td></tr>
<tr><td><b>Wheel</b></td><td>zoom &nbsp;·&nbsp; <b>0</b> fit &nbsp;·&nbsp; middle button drags</td></tr>
<tr><td><b>%(undo)s / %(redo)s</b></td><td>undo / redo</td></tr>
<tr><td><b>%(open)s · %(export)s</b></td><td>add images · export PDF</td></tr>
</table>"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setAcceptDrops(True)
        self.ajustes = app_settings()
        self.exts = supported_exts()
        self.pages: list = []                   # {"id", "path", "draw", "size"}
        self.thumbs: dict = {}                  # ruta -> miniatura sin dibujos
        self.current: str | None = None         # id de la pagina en el lienzo
        self.undo_stack: list = []
        self.redo_stack: list = []
        self.dirty = False
        self.project_path: str | None = None
        self._img_cache = (None, None)          # (ruta, QImage) de la pagina actual
        self.sel: str | None = None             # id del dibujo seleccionado
        self._move = None                       # (foto para deshacer, dibujo original)
        self.pool = QThreadPool(self)
        self._build_ui()
        self._build_menu()
        self._restore()
        self._update_state()
        prune_pasted(set())

    # -- interfaz ---------------------------------------------------------- #
    def _build_ui(self):
        centro = QWidget()
        raiz = QVBoxLayout(centro)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        barra = QWidget()
        barra.setObjectName("toolbar")
        fila = QHBoxLayout(barra)
        fila.setContentsMargins(10, 6, 10, 6)
        fila.setSpacing(4)

        def boton(icono, texto, tip, fn, primario=False):
            b = QPushButton("  " + texto if icono else texto)
            if icono:
                b.setProperty("icon_name", icono)
                b.setIcon(tool_icon(icono))
            b.setToolTip(tip)
            b.clicked.connect(fn)
            if primario:
                b.setProperty("primary", True)
            return b

        self.b_add = boton("add", "Add images", "Add images or folders (%s)"
                           % keys_text("Ctrl+O"), self.add_dialog)
        fila.addWidget(self.b_add)
        self.b_paste = boton("paste", "Paste", "Paste an image or copied files as new pages, "
                             "or copied drawings onto this page (%s)" % keys_text("Ctrl+V"),
                             self.paste)
        fila.addWidget(self.b_paste)
        fila.addSpacing(10)

        self.grupo = QButtonGroup(self)
        self.grupo.setExclusive(True)
        self.tool_buttons = {}
        for tool, icono, nombre, atajo, tip in TOOLS:
            b = QToolButton()
            b.setProperty("icon_name", icono)
            b.setIcon(tool_icon(icono))
            b.setIconSize(QSize(20, 20))
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setToolTip("%s (%s) — %s" % (nombre, atajo, tip))
            # toggled y no clicked: tambien llega si se pulsa por accesibilidad o teclado
            b.toggled.connect(lambda on, t=tool: on and self.set_tool(t))
            self.grupo.addButton(b)
            fila.addWidget(b)
            self.tool_buttons[tool] = b
            sc = QShortcut(QKeySequence(atajo), self)
            sc.activated.connect(lambda t=tool: self.set_tool(t))
        fila.addSpacing(10)

        self.grupo_color = QButtonGroup(self)
        self.grupo_color.setExclusive(True)
        self.color_buttons = {}
        for nombre, hexa in DRAW_COLORS:
            b = QToolButton()
            b.setCheckable(True)
            b.setIcon(swatch_icon(hexa))
            b.setIconSize(QSize(18, 18))
            b.setToolTip(nombre)
            b.setAutoRaise(True)
            b.toggled.connect(lambda on, h=hexa: on and self.set_color(QColor(h)))
            self.grupo_color.addButton(b)
            self.color_buttons[hexa] = b
            fila.addWidget(b)
        self.b_color = QToolButton()
        self.b_color.setText("…")
        self.b_color.setToolTip("Pick another colour")
        self.b_color.setAutoRaise(True)
        self.b_color.clicked.connect(self.pick_color)
        fila.addWidget(self.b_color)
        fila.addSpacing(8)
        fila.addWidget(QLabel("Size"))
        self.sld_width = QSlider(Qt.Orientation.Horizontal)
        self.sld_width.setRange(1, 30)
        self.sld_width.setFixedWidth(100)
        self.sld_width.setToolTip("Line thickness (it scales with the image)")
        self.sld_width.valueChanged.connect(self.set_width)
        fila.addWidget(self.sld_width)
        fila.addSpacing(8)

        self.b_undo = QToolButton()
        self.b_undo.setProperty("icon_name", "undo")
        self.b_undo.setIcon(tool_icon("undo"))
        self.b_undo.setAutoRaise(True)
        self.b_undo.setToolTip("Undo (%s)" % keys_text("Ctrl+Z"))
        self.b_undo.clicked.connect(self.undo)
        self.b_redo = QToolButton()
        self.b_redo.setProperty("icon_name", "redo")
        self.b_redo.setIcon(tool_icon("redo"))
        self.b_redo.setAutoRaise(True)
        self.b_redo.setToolTip("Redo (%s)" % keys_text("Ctrl+Shift+Z"))
        self.b_redo.clicked.connect(self.redo)
        self.b_clear = QToolButton()
        self.b_clear.setProperty("icon_name", "clear")
        self.b_clear.setIcon(tool_icon("clear"))
        self.b_clear.setAutoRaise(True)
        self.b_clear.setToolTip("Clear the drawings of this page")
        self.b_clear.clicked.connect(self.clear_drawings)
        for b in (self.b_undo, self.b_redo, self.b_clear):
            fila.addWidget(b)
        fila.addStretch(1)

        self.b_theme = QToolButton()
        self.b_theme.setAutoRaise(True)
        self.b_theme.setToolTip("Light / dark theme")
        self.b_theme.clicked.connect(self.toggle_theme)
        fila.addWidget(self.b_theme)
        self.b_export = boton("pdf", "Export PDF", "Export every page as one PDF (%s)"
                              % keys_text("Ctrl+E"), self.export_dialog, primario=True)
        fila.addWidget(self.b_export)
        raiz.addWidget(barra)

        self.split = QSplitter(Qt.Orientation.Horizontal)
        izq = QWidget()
        li = QVBoxLayout(izq)
        li.setContentsMargins(8, 8, 0, 8)
        li.setSpacing(4)
        self.lbl_pages = QLabel("PAGES")
        self.lbl_pages.setProperty("role", "section")
        li.addWidget(self.lbl_pages)
        self.list = PageList()
        self.list.currentItemChanged.connect(self._on_current_item)
        self.list.files_dropped.connect(lambda rutas, fila: self.add_paths(rutas, fila))
        self.list.reordered.connect(self._on_reordered)
        self.list.delete_pressed.connect(self.remove_selected)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._page_menu)
        li.addWidget(self.list, 1)
        self.split.addWidget(izq)

        self.stack = QStackedWidget()
        hint = QWidget()
        hint.setObjectName("hint")
        hl = QVBoxLayout(hint)
        hl.addStretch(1)
        icono = QLabel()
        icono.setPixmap(app_pixmap(96))
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(icono)
        t = QLabel("Drag images here")
        t.setProperty("role", "hint-title")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(t)
        s = QLabel("Images or whole folders. Each image becomes a page of the PDF.")
        s.setProperty("role", "hint")
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(s)
        b = boton("add", "Add images…", "", self.add_dialog)
        b.setFixedWidth(180)
        fila_b = QHBoxLayout()
        fila_b.addStretch(1)
        fila_b.addWidget(b)
        fila_b.addStretch(1)
        hl.addSpacing(10)
        hl.addLayout(fila_b)
        hl.addStretch(2)
        self.stack.addWidget(hint)
        self.canvas = Canvas()
        self.canvas.drawn.connect(self.on_drawn)
        self.canvas.erase_at.connect(self.on_erase)
        self.canvas.zoom_changed.connect(self._show_zoom)
        self.canvas.picker = self._pick
        self.canvas.hover = self._hover
        self.canvas.move_by.connect(self._on_move_by)
        self.canvas.move_done.connect(self._on_move_done)
        self.canvas.edit_at.connect(self._on_edit_at)
        self.canvas.delete_key.connect(self.delete_shape)
        self.canvas.escape_key.connect(lambda: self.select_shape(None))
        self.stack.addWidget(self.canvas)
        self.split.addWidget(self.stack)

        der = QWidget()
        ld = QVBoxLayout(der)
        ld.setContentsMargins(0, 8, 8, 8)
        ld.setSpacing(4)
        et = QLabel("LAYERS")
        et.setProperty("role", "section")
        et.setToolTip("Top of the list = in front. Drag to reorder, click the eye to hide.")
        ld.addWidget(et)
        self.layers = LayerList()
        self.layers.setToolTip("Top of the list = in front. Drag to reorder; click the eye "
                               "to hide (hidden layers are left out of the PDF).")
        self.layers.itemSelectionChanged.connect(self._on_layer_selected)
        self.layers.eye_clicked.connect(self.toggle_visibility)
        self.layers.itemDoubleClicked.connect(self._on_layer_double_click)
        self.layers.reordered.connect(self._on_layers_reordered)
        self.layers.delete_pressed.connect(self.delete_shape)
        ld.addWidget(self.layers, 1)
        self.lbl_no_layers = QLabel("Nothing drawn on this page yet.")
        self.lbl_no_layers.setProperty("role", "empty")
        self.lbl_no_layers.setWordWrap(True)
        ld.addWidget(self.lbl_no_layers)
        botones_capa = QHBoxLayout()
        botones_capa.setSpacing(2)
        self.b_raise = self._icon_button("raise", "Bring forward (%s)" % keys_text("Ctrl+]"),
                                         lambda: self.restack(1))
        self.b_lower = self._icon_button("lower", "Send backward (%s)" % keys_text("Ctrl+["),
                                         lambda: self.restack(-1))
        self.b_del_layer = self._icon_button("trash", "Delete the selected drawing (Delete)",
                                             self.delete_shape)
        for b in (self.b_raise, self.b_lower):
            botones_capa.addWidget(b)
        botones_capa.addStretch(1)
        botones_capa.addWidget(self.b_del_layer)
        ld.addLayout(botones_capa)
        self.split.addWidget(der)
        self.split.setStretchFactor(1, 1)
        self.split.setCollapsible(1, False)
        self.split.setSizes([200, 900, 220])
        raiz.addWidget(self.split, 1)
        self.setCentralWidget(centro)

        self.lbl_zoom = QLabel("")
        self.b_fit = QToolButton()
        self.b_fit.setProperty("icon_name", "fit")
        self.b_fit.setIcon(tool_icon("fit"))
        self.b_fit.setAutoRaise(True)
        self.b_fit.setToolTip("Fit the page in the window (0)")
        self.b_fit.clicked.connect(self.canvas.fit)
        self.statusBar().addPermanentWidget(self.lbl_zoom)
        self.statusBar().addPermanentWidget(self.b_fit)

        for sec, fn in (("0", self.canvas.fit),
                        ("Right", lambda: self.step(1)), ("Left", lambda: self.step(-1)),
                        ("PgDown", lambda: self.step(1)), ("PgUp", lambda: self.step(-1)),
                        ("Down", lambda: self.step(1)), ("Up", lambda: self.step(-1)),
                        ("Ctrl+=", lambda: self.canvas.zoom_by(1.25)),
                        ("Ctrl++", lambda: self.canvas.zoom_by(1.25)),
                        ("Ctrl+-", lambda: self.canvas.zoom_by(0.8))):
            sc = QShortcut(QKeySequence(sec), self)
            sc.activated.connect(fn)

    def _build_menu(self):
        mb = self.menuBar()
        archivo = mb.addMenu("&File")

        def accion(menu, texto, fn, atajo=None):
            a = QAction(texto, self)
            if atajo is not None:
                a.setShortcut(QKeySequence(atajo))
            a.triggered.connect(fn)
            menu.addAction(a)
            return a

        accion(archivo, "New", self.new_project, QKeySequence.StandardKey.New)
        accion(archivo, "Add images…", self.add_dialog, QKeySequence.StandardKey.Open)
        accion(archivo, "Add a folder…", self.add_folder_dialog)
        archivo.addSeparator()
        accion(archivo, "Open project…", self.open_project_dialog, "Ctrl+Shift+O")
        accion(archivo, "Save project", self.save_project, QKeySequence.StandardKey.Save)
        accion(archivo, "Save project as…", self.save_project_as, "Ctrl+Shift+S")
        archivo.addSeparator()
        self.act_export = accion(archivo, "Export PDF…", self.export_dialog, "Ctrl+E")
        archivo.addSeparator()
        accion(archivo, "Quit", self.close, QKeySequence.StandardKey.Quit)

        editar = mb.addMenu("&Edit")
        self.act_undo = accion(editar, "Undo", self.undo, QKeySequence.StandardKey.Undo)
        self.act_redo = accion(editar, "Redo", self.redo)
        # Ctrl+Y en Windows y Ctrl+Mayus+Z en todos, sin repetir ninguna: un
        # atajo puesto dos veces es ambiguo y Qt no ejecuta ninguno
        rehacer = list(QKeySequence.keyBindings(QKeySequence.StandardKey.Redo))
        if QKeySequence("Ctrl+Shift+Z") not in rehacer:
            rehacer.append(QKeySequence("Ctrl+Shift+Z"))
        self.act_redo.setShortcuts(rehacer)
        editar.addSeparator()
        accion(editar, "Copy drawing", self.copy_shape, QKeySequence.StandardKey.Copy)
        accion(editar, "Paste", self.paste, QKeySequence.StandardKey.Paste)
        accion(editar, "Duplicate drawing", self.duplicate_shape, "Ctrl+D")
        accion(editar, "Delete drawing", self.delete_shape)
        accion(editar, "Hide / show drawing", self.toggle_visibility, "Ctrl+Shift+H")
        editar.addSeparator()
        # [ y ] piden Alt en los teclados espanoles: tambien con Mayus + flechas
        accion(editar, "Bring forward", lambda: self.restack(1)).setShortcuts(
            [QKeySequence("Ctrl+]"), QKeySequence("Ctrl+Shift+Up")])
        accion(editar, "Send backward", lambda: self.restack(-1)).setShortcuts(
            [QKeySequence("Ctrl+["), QKeySequence("Ctrl+Shift+Down")])
        accion(editar, "Bring to front", lambda: self.restack(10 ** 6), "Ctrl+Shift+]")
        accion(editar, "Send to back", lambda: self.restack(-10 ** 6), "Ctrl+Shift+[")

        pag = mb.addMenu("&Page")
        accion(pag, "Clear drawings on this page", self.clear_drawings)
        accion(pag, "Remove selected pages", self.remove_selected)
        accion(pag, "Move page up", lambda: self.move_current(-1), "Ctrl+Up")
        accion(pag, "Move page down", lambda: self.move_current(1), "Ctrl+Down")

        ver = mb.addMenu("&View")
        accion(ver, "Fit page", self.canvas.fit)
        accion(ver, "Light / dark theme", self.toggle_theme, "Ctrl+T")
        ayuda = mb.addMenu("&Help")
        accion(ayuda, "How it works", self.show_help, "F1")
        accion(ayuda, "About %s" % APP_NAME, self.show_about)

    def _icon_button(self, icono: str, tip: str, fn) -> QToolButton:
        b = QToolButton()
        b.setProperty("icon_name", icono)
        b.setIcon(tool_icon(icono))
        b.setAutoRaise(True)
        b.setToolTip(tip)
        b.clicked.connect(fn)
        return b

    def _restore(self):
        geo = self.ajustes.value("window/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            self.resize(1300, 850)
        self.sld_width.setValue(int(self.ajustes.value("draw/width", 6)))
        self.set_color(QColor(self.ajustes.value("draw/color", DRAW_COLORS[0][1])))
        self.set_tool(None)
        self._retheme()

    # -- tema -------------------------------------------------------------- #
    def toggle_theme(self):
        apply_theme("light" if _theme == "dark" else "dark")
        self.ajustes.setValue("theme", _theme)
        self._retheme()

    def _retheme(self):
        for w in self.findChildren(QPushButton) + self.findChildren(QToolButton):
            nombre = w.property("icon_name")
            if nombre:
                w.setIcon(tool_icon(nombre))
        self.b_theme.setIcon(tool_icon("sun" if _theme == "dark" else "moon"))
        self.canvas.viewport().update()
        for w in self.findChildren(QPushButton):  # el QSS de "primary" se reaplica
            w.style().unpolish(w)
            w.style().polish(w)

    # -- herramientas ------------------------------------------------------ #
    def set_tool(self, tool):
        if tool is not None and self.sel:
            self.select_shape(None)             # al dibujar, nada seleccionado
        self.canvas.set_tool(tool)
        self.tool_buttons[tool].setChecked(True)

    def set_color(self, c: QColor):
        if self.canvas.tool is None and self.recolor_shape(c):
            self._check_color_button(c)
            return
        self.canvas.color = QColor(c)
        self.ajustes.setValue("draw/color", c.name())
        b = self.color_buttons.get(c.name().lower())
        if b is not None:
            b.setChecked(True)
            self.b_color.setIcon(QIcon())
            self.b_color.setText("…")
        else:                                   # un color de fuera de la paleta
            self.grupo_color.setExclusive(False)
            for otro in self.grupo_color.buttons():
                otro.setChecked(False)
            self.grupo_color.setExclusive(True)
            self.b_color.setText("")
            self.b_color.setIcon(swatch_icon(c.name()))
        if self.canvas.tool in (None, "goma"):  # elegir color es querer pintar
            self.set_tool("trazo")

    def _check_color_button(self, c: QColor):
        b = self.color_buttons.get(c.name().lower())
        if b is not None and not b.isChecked():
            b.blockSignals(True)
            b.setChecked(True)
            b.blockSignals(False)

    def pick_color(self):
        c = QColorDialog.getColor(self.canvas.color, self, "Drawing colour")
        if c.isValid():
            self.set_color(c)

    def set_width(self, v: int):
        self.canvas.width = v
        self.ajustes.setValue("draw/width", v)

    # -- paginas ----------------------------------------------------------- #
    def page(self, pid: str | None) -> dict | None:
        for p in self.pages:
            if p["id"] == pid:
                return p
        return None

    def add_dialog(self):
        filtro = "Images (%s)" % " ".join("*" + e for e in sorted(self.exts))
        rutas, _ = QFileDialog.getOpenFileNames(self, "Add images",
                                                self.ajustes.value("dirs/images", ""), filtro)
        if rutas:
            self.ajustes.setValue("dirs/images", os.path.dirname(rutas[0]))
            self.add_paths(rutas)

    def add_folder_dialog(self):
        carpeta = QFileDialog.getExistingDirectory(self, "Add a folder",
                                                   self.ajustes.value("dirs/images", ""))
        if carpeta:
            self.ajustes.setValue("dirs/images", carpeta)
            self.add_paths([carpeta])

    def add_paths(self, rutas: list, fila: int | None = None):
        # un proyecto soltado en la ventana se abre, no se mezcla
        proyectos = [r for r in rutas if r.lower().endswith(PROJECT_EXTS)]
        if proyectos and len(rutas) == 1:
            if self.maybe_save():
                self.load_project(proyectos[0])
            return
        imagenes = scan_paths(rutas, self.exts)
        if not imagenes:
            self.statusBar().showMessage("No images there (%s)."
                                         % ", ".join(sorted(e[1:] for e in self.exts)), 6000)
            return
        self.push_undo()
        fila = len(self.pages) if fila is None else max(0, min(fila, len(self.pages)))
        nuevas = [{"id": uuid.uuid4().hex, "path": os.path.abspath(r), "draw": [], "size": None}
                  for r in imagenes]
        self.pages[fila:fila] = nuevas
        self._rebuild_list(select=nuevas[0]["id"])
        self._mark_dirty()
        self.statusBar().showMessage("Added %d image%s." % (len(nuevas), "" if len(nuevas) == 1
                                                            else "s"), 4000)

    def _rebuild_list(self, select: str | None = None):
        self.list.blockSignals(True)
        self.list.clear()
        for i, p in enumerate(self.pages):
            item = QListWidgetItem()
            item.setData(PAGE_ROLE, p["id"])
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
            self.list.addItem(item)
            self._refresh_item(item, p, i)
        self.list.blockSignals(False)
        objetivo = select if self.page(select) else (self.current if self.page(self.current)
                                                    else (self.pages[0]["id"] if self.pages
                                                          else None))
        if objetivo:
            for i in range(self.list.count()):
                if self.list.item(i).data(PAGE_ROLE) == objetivo:
                    self.list.setCurrentRow(i)
                    break
            if self.current != objetivo:
                self.show_page(objetivo)
            else:
                self.show_page(objetivo, recargar=False)
        else:
            self.show_page(None)
        self._update_state()

    def _refresh_item(self, item: QListWidgetItem, p: dict, i: int):
        item.setText("%d · %s" % (i + 1, os.path.basename(p["path"])))
        item.setToolTip(p["path"])
        base = self.thumbs.get(p["path"])
        if base is None:
            self._request_thumb(p["path"])
            pm = QPixmap(ICON_BOX, ICON_BOX * 2 // 3)
            pm.fill(QColor(theme_color("raised")))
            item.setIcon(QIcon(pm))
            return
        img = QImage(base).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        if p.get("draw") and p.get("size"):
            pt = QPainter(img)
            pt.setClipRect(img.rect())
            pt.scale(img.width() / p["size"][0], img.height() / p["size"][1])
            paint_shapes(pt, p["draw"])
            pt.end()
        # centrada en un cuadrado fijo: todas las paginas ocupan lo mismo
        dpr = max(1.0, self.list.devicePixelRatioF())
        lado = round(ICON_BOX * dpr)
        img = img.scaled(lado, lado, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
        pm = QPixmap(lado, lado)
        pm.fill(Qt.GlobalColor.transparent)
        pt = QPainter(pm)
        pt.drawImage((lado - img.width()) // 2, (lado - img.height()) // 2, img)
        pt.end()
        pm.setDevicePixelRatio(dpr)
        item.setIcon(QIcon(pm))

    def _request_thumb(self, path: str):
        if path in self.thumbs or path in getattr(self, "_pedidas", set()):
            return
        self._pedidas = getattr(self, "_pedidas", set())
        self._pedidas.add(path)
        if not os.path.exists(path):
            self._on_thumb(path, missing_image(THUMB_SIZE, THUMB_SIZE * 3 // 4), None)
            return
        t = ThumbTask(path)
        t.signals.done.connect(self._on_thumb)
        self.pool.start(t)

    @Slot(str, QImage, object)
    def _on_thumb(self, path: str, img: QImage, size):
        self._pedidas.discard(path)
        self.thumbs[path] = img if not img.isNull() else missing_image(THUMB_SIZE, THUMB_SIZE * 3 // 4)
        for i, p in enumerate(self.pages):
            if p["path"] == path:
                if size and not p.get("size"):
                    p["size"] = list(size)
                self._refresh_item(self.list.item(i), p, i)

    def _refresh_current_item(self):
        for i, p in enumerate(self.pages):
            if p["id"] == self.current:
                self._refresh_item(self.list.item(i), p, i)
                return

    def _on_current_item(self, item, _prev):
        if item is not None:
            self.show_page(item.data(PAGE_ROLE))

    def show_page(self, pid: str | None, recargar: bool = True):
        if pid != self.current:
            self.sel = None
        self.current = pid
        p = self.page(pid)
        if p is not None and self.sel and not any(f.get("id") == self.sel for f in p["draw"]):
            self.sel = None
        self.canvas.notes.selected = self.sel
        self._rebuild_layers()
        if p is None:
            self.stack.setCurrentIndex(0)
            self.lbl_zoom.setText("")
            self._update_state()
            return
        self.stack.setCurrentIndex(1)
        if recargar or self._img_cache[0] != p["path"]:
            if self._img_cache[0] == p["path"]:
                img = self._img_cache[1]
            else:
                img = read_image(p["path"]) if os.path.exists(p["path"]) else QImage()
                if img.isNull():
                    img = missing_image()
                    if not p.get("size"):
                        p["size"] = [img.width(), img.height()]
                self._img_cache = (p["path"], img)
            if not p.get("size"):
                tam = image_size(p["path"]) if os.path.exists(p["path"]) else None
                p["size"] = list(tam) if tam else [img.width(), img.height()]
            self.canvas.show_page(img, tuple(p["size"]), p["draw"])
        else:
            self.canvas.refresh_notes(p["draw"])
        i = self.pages.index(p)
        self.statusBar().showMessage("Page %d of %d  ·  %s  ·  %d × %d px"
                                     % (i + 1, len(self.pages), p["path"], *p["size"]))
        self._update_state()

    def step(self, delta: int):
        if not self.pages:
            return
        fila = max(0, min(self.list.currentRow() + delta, len(self.pages) - 1))
        self.list.setCurrentRow(fila)
        self.list.scrollToItem(self.list.item(fila))

    def _on_reordered(self):
        orden = [self.list.item(i).data(PAGE_ROLE) for i in range(self.list.count())]
        if orden == [p["id"] for p in self.pages]:
            return
        self.push_undo()
        por_id = {p["id"]: p for p in self.pages}
        self.pages = [por_id[i] for i in orden]
        self._mark_dirty()
        # los numeros de pagina cambian: se rehacen los rotulos
        QTimer.singleShot(0, lambda: self._rebuild_list(select=self.current))

    def move_current(self, delta: int):
        p = self.page(self.current)
        if p is None:
            return
        i = self.pages.index(p)
        j = i + delta
        if not 0 <= j < len(self.pages):
            return
        self.push_undo()
        self.pages[i], self.pages[j] = self.pages[j], self.pages[i]
        self._mark_dirty()
        self._rebuild_list(select=p["id"])

    def remove_selected(self):
        ids = {it.data(PAGE_ROLE) for it in self.list.selectedItems()}
        if not ids and self.current:
            ids = {self.current}
        if not ids:
            return
        self.push_undo()
        quedan = [p for p in self.pages if p["id"] not in ids]
        siguiente = None
        if self.current in ids:
            filas = [i for i, p in enumerate(self.pages) if p["id"] in ids]
            if quedan:
                siguiente = quedan[min(filas[0], len(quedan) - 1)]["id"]
            self.current = None
        self.pages = quedan
        self._mark_dirty()
        self._rebuild_list(select=siguiente)
        self.statusBar().showMessage("Removed %d page%s (%s undoes it)."
                                     % (len(ids), "" if len(ids) == 1 else "s",
                                        keys_text("Ctrl+Z")), 5000)

    def _page_menu(self, pos):
        if self.list.itemAt(pos) is None:
            return
        m = QMenu(self)
        m.addAction("Clear drawings", self.clear_drawings)
        m.addAction("Move up", lambda: self.move_current(-1))
        m.addAction("Move down", lambda: self.move_current(1))
        m.addSeparator()
        n = len(self.list.selectedItems())
        m.addAction("Remove %s" % ("page" if n <= 1 else "%d pages" % n), self.remove_selected)
        m.exec(self.list.viewport().mapToGlobal(pos))

    # -- dibujos ----------------------------------------------------------- #
    @Slot(dict)
    def on_drawn(self, forma: dict):
        p = self.page(self.current)
        if p is None:
            return
        if forma["tipo"] == "texto":
            txt, ok = QInputDialog.getMultiLineText(self, "Text", "What do you want to write?")
            if not ok or not txt.strip():
                return
            forma = dict(forma, texto=txt.rstrip())
        self.push_undo()
        p["draw"] = p["draw"] + [forma]
        self._after_draw(p)

    @Slot(QPointF, float)
    def on_erase(self, punto: QPointF, tolerancia: float):
        p = self.page(self.current)
        if p is None:
            return
        i = shape_at(p["draw"], punto, tolerancia)     # el de mas arriba primero
        if i is not None:
            self.push_undo()
            p["draw"] = p["draw"][:i] + p["draw"][i + 1:]
            self._after_draw(p)

    def clear_drawings(self):
        p = self.page(self.current)
        if p is None or not p["draw"]:
            return
        self.push_undo()
        p["draw"] = []
        self._after_draw(p)

    def _after_draw(self, p: dict):
        if self.sel and not any(f.get("id") == self.sel for f in p["draw"]):
            self.sel = None
        self.canvas.notes.selected = self.sel
        self.canvas.refresh_notes(p["draw"])
        self._refresh_current_item()
        self._rebuild_layers()
        self._mark_dirty()

    # -- seleccion y capas ------------------------------------------------- #
    def _shape_index(self, p: dict | None, sid: str | None):
        if p is None or not sid:
            return None
        for i, f in enumerate(p["draw"]):
            if f.get("id") == sid:
                return i
        return None

    def selected_shape(self) -> dict | None:
        p = self.page(self.current)
        i = self._shape_index(p, self.sel)
        return None if i is None else p["draw"][i]

    def select_shape(self, sid: str | None):
        self.sel = sid
        self.canvas.notes.selected = sid
        self.canvas.notes.update()
        self.layers.blockSignals(True)
        self.layers.clearSelection()
        for i in range(self.layers.count()):
            it = self.layers.item(i)
            if it.data(SHAPE_ROLE) == sid:
                it.setSelected(True)
                self.layers.setCurrentItem(it)
                self.layers.scrollToItem(it)
                break
        self.layers.blockSignals(False)
        self._update_state()

    def _rebuild_layers(self):
        p = self.page(self.current)
        formas = p["draw"] if p else []
        self.layers.blockSignals(True)
        self.layers.clear()
        for f in reversed(formas):                     # arriba de la lista = encima
            it = QListWidgetItem(layer_icon(f), shape_label(f))
            it.setData(SHAPE_ROLE, f.get("id"))
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
            it.setToolTip("Click the eye to %s it%s" % (
                "show" if f.get("oculto") else "hide",
                "" if f.get("oculto") else " (it is left out of the PDF too)"))
            if f.get("oculto"):
                it.setForeground(QColor(theme_color("dim")))
            self.layers.addItem(it)
            if f.get("id") == self.sel:
                it.setSelected(True)
                self.layers.setCurrentItem(it)
        self.layers.blockSignals(False)
        self.layers.setVisible(bool(formas))
        self.lbl_no_layers.setVisible(p is not None and not formas)

    def _pick(self, punto: QPointF, tolerancia: float) -> bool:
        """Con la flecha: pincha el dibujo de encima y lo prepara para moverlo."""
        p = self.page(self.current)
        i = shape_at(p["draw"], punto, tolerancia, interior=True) if p else None
        if i is None:
            self.select_shape(None)
            return False
        self.select_shape(p["draw"][i]["id"])
        self._move = (self._snapshot(), p["draw"][i], False)
        return True

    def _hover(self, punto: QPointF, tolerancia: float) -> bool:
        p = self.page(self.current)
        return bool(p) and shape_at(p["draw"], punto, tolerancia, interior=True) is not None

    @Slot(float, float)
    def _on_move_by(self, dx: float, dy: float):
        p = self.page(self.current)
        i = self._shape_index(p, self.sel)
        if i is None or self._move is None:
            return
        foto, original, _ = self._move
        # siempre desde el original: el arrastre entero es un solo paso de deshacer
        p["draw"][i] = translate_shape(original, dx, dy)
        self._move = (foto, original, True)
        self.canvas.refresh_notes(p["draw"])

    @Slot()
    def _on_move_done(self):
        if self._move is None:
            return
        foto, _, movido = self._move
        self._move = None
        if movido:
            self.undo_stack.append(foto)
            del self.undo_stack[:-UNDO_LIMIT]
            self.redo_stack.clear()
            self._refresh_current_item()
            self._mark_dirty()

    @Slot(QPointF, float)
    def _on_edit_at(self, punto: QPointF, tolerancia: float):
        p = self.page(self.current)
        i = shape_at(p["draw"], punto, tolerancia, interior=True) if p else None
        if i is not None:
            self.select_shape(p["draw"][i]["id"])
            self.edit_text()

    def edit_text(self):
        f = self.selected_shape()
        if f is None or f.get("tipo") != "texto":
            return
        txt, ok = QInputDialog.getMultiLineText(self, "Text", "Change the text:",
                                                f.get("texto", ""))
        if ok and txt.strip() and txt.rstrip() != f.get("texto"):
            self._replace_shape(dict(f, texto=txt.rstrip()))

    def _replace_shape(self, nueva: dict):
        p = self.page(self.current)
        i = self._shape_index(p, nueva.get("id"))
        if i is None:
            return
        self.push_undo()
        p["draw"] = p["draw"][:i] + [nueva] + p["draw"][i + 1:]
        self._after_draw(p)

    def recolor_shape(self, c: QColor) -> bool:
        f = self.selected_shape()
        if f is None:
            return False
        if f.get("color", "").lower() != c.name().lower():
            self._replace_shape(dict(f, color=c.name()))
        return True

    def delete_shape(self):
        p = self.page(self.current)
        i = self._shape_index(p, self.sel)
        if i is None:
            return
        self.push_undo()
        p["draw"] = p["draw"][:i] + p["draw"][i + 1:]
        self.sel = None
        self._after_draw(p)

    def restack(self, delta: int):
        """Sube (delta > 0) o baja la capa seleccionada; uno grande la lleva al extremo."""
        p = self.page(self.current)
        i = self._shape_index(p, self.sel)
        if i is None:
            return
        j = max(0, min(len(p["draw"]) - 1, i + delta))
        if j == i:
            return
        self.push_undo()
        formas = list(p["draw"])
        formas.insert(j, formas.pop(i))
        p["draw"] = formas
        self._after_draw(p)

    def _on_layer_selected(self):
        items = self.layers.selectedItems()
        self.select_shape(items[0].data(SHAPE_ROLE) if items else None)

    def toggle_visibility(self, sid: str | None = None):
        """Oculta o muestra un dibujo (por defecto, el seleccionado)."""
        p = self.page(self.current)
        i = self._shape_index(p, sid or self.sel)
        if i is None:
            return
        f = p["draw"][i]
        nueva = ({k: v for k, v in f.items() if k != "oculto"} if f.get("oculto")
                 else dict(f, oculto=True))
        # fuera del clic: rehacer la lista borra el elemento que lo recibio
        QTimer.singleShot(0, lambda: self._replace_shape(nueva))

    def _on_layer_double_click(self, item: QListWidgetItem):
        self.select_shape(item.data(SHAPE_ROLE))
        self.edit_text()

    def _on_layers_reordered(self):
        p = self.page(self.current)
        if p is None:
            return
        orden = [self.layers.item(i).data(SHAPE_ROLE) for i in range(self.layers.count())]
        por_id = {f.get("id"): f for f in p["draw"]}
        nuevas = [por_id[sid] for sid in reversed(orden) if sid in por_id]
        if len(nuevas) != len(p["draw"]) or nuevas == p["draw"]:
            QTimer.singleShot(0, self._rebuild_layers)
            return
        self.push_undo()
        p["draw"] = nuevas
        QTimer.singleShot(0, lambda: self._after_draw(p))

    # -- portapapeles ------------------------------------------------------ #
    def copy_shape(self):
        f = self.selected_shape()
        if f is None:
            self.statusBar().showMessage("Select a drawing first (V, then click it).", 4000)
            return
        datos = QMimeData()
        datos.setData(SHAPES_MIME, QByteArray(json.dumps([f]).encode("utf-8")))
        QApplication.clipboard().setMimeData(datos)
        self.statusBar().showMessage("Copied: %s" % shape_label(f), 3000)

    def duplicate_shape(self):
        f = self.selected_shape()
        if f is not None:
            self._paste_shapes([f])

    def _paste_shapes(self, formas: list):
        p = self.page(self.current)
        if p is None or not formas:
            return
        d = max(p.get("size") or [1000]) * 0.02         # un poco desplazados, para verlos
        nuevas = [dict(translate_shape(f, d, d), id=new_shape_id()) for f in formas]
        self.push_undo()
        p["draw"] = p["draw"] + nuevas
        self.sel = nuevas[-1]["id"]
        self._after_draw(p)
        if self.canvas.tool is not None:
            self.set_tool(None)                        # para poder moverlos ya

    def paste(self):
        """Pega lo que haya: dibujos copiados, archivos copiados o una imagen."""
        datos = QApplication.clipboard().mimeData()
        if datos is None:
            return
        if datos.hasFormat(SHAPES_MIME) and self.page(self.current) is not None:
            try:
                formas = json.loads(bytes(datos.data(SHAPES_MIME)).decode("utf-8"))
                self._paste_shapes([f for f in formas if isinstance(f, dict) and f.get("tipo")])
                return
            except ValueError:
                pass
        p = self.page(self.current)
        fila = self.pages.index(p) + 1 if p else len(self.pages)
        # archivos copiados en el Finder o el Explorador (traen tambien su icono
        # como imagen, por eso se miran antes)
        rutas = [u.toLocalFile() for u in datos.urls() if u.isLocalFile()] if datos.hasUrls() else []
        rutas = [r for r in rutas if os.path.exists(r)]
        if rutas:
            self.add_paths(rutas, fila)
            return
        if datos.hasImage():
            img = QApplication.clipboard().image()
            if not img.isNull():
                ruta = self._save_pasted(img)
                if ruta:
                    self.add_paths([ruta], fila)
                return
        self.statusBar().showMessage("There is no image to paste.", 4000)

    def _save_pasted(self, img: QImage) -> str | None:
        base = pasted_dir() / time.strftime("pasted-%Y-%m-%d-%H%M%S")
        ruta, n = Path(str(base) + ".png"), 2
        while ruta.exists():
            ruta, n = Path("%s-%d.png" % (base, n)), n + 1
        if not img.save(str(ruta), "PNG"):
            QMessageBox.warning(self, "Paste", "Could not save the pasted image in\n%s"
                                % pasted_dir())
            return None
        return str(ruta)

    # -- deshacer ---------------------------------------------------------- #
    def _snapshot(self):
        # los dibujos nunca se cambian en su sitio (se sustituyen por copias),
        # asi que basta con copiar las listas
        return ([{"id": p["id"], "path": p["path"], "draw": list(p["draw"]),
                  "size": p.get("size")} for p in self.pages], self.current)

    def push_undo(self):
        self.undo_stack.append(self._snapshot())
        del self.undo_stack[:-UNDO_LIMIT]
        self.redo_stack.clear()
        self._update_state()

    def _restore_snapshot(self, snap):
        paginas, actual = snap
        # el tamano pudo llegar despues de la foto: no se pierde
        tamanos = {p["id"]: p.get("size") for p in self.pages}
        self.pages = [dict(p, draw=list(p["draw"]), size=p.get("size") or tamanos.get(p["id"]))
                      for p in paginas]
        self._mark_dirty()
        self._rebuild_list(select=actual)

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self._snapshot())
            self._restore_snapshot(self.undo_stack.pop())

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self._snapshot())
            self._restore_snapshot(self.redo_stack.pop())

    # -- estado ------------------------------------------------------------ #
    def _mark_dirty(self, sucio: bool = True):
        self.dirty = sucio
        self._update_state()

    def _update_state(self):
        hay = bool(self.pages)
        p = self.page(self.current)
        self.b_export.setEnabled(hay)
        self.act_export.setEnabled(hay) if hasattr(self, "act_export") else None
        self.b_undo.setEnabled(bool(self.undo_stack))
        self.b_redo.setEnabled(bool(self.redo_stack))
        if hasattr(self, "act_undo"):
            self.act_undo.setEnabled(bool(self.undo_stack))
            self.act_redo.setEnabled(bool(self.redo_stack))
        self.b_clear.setEnabled(bool(p and p["draw"]))
        hay_sel = self._shape_index(p, self.sel) is not None
        for b in (self.b_raise, self.b_lower, self.b_del_layer):
            b.setEnabled(hay_sel)
        self.lbl_pages.setText("PAGES  (%d)" % len(self.pages) if hay else "PAGES")
        nombre = Path(self.project_path).stem if self.project_path else "Untitled"
        self.setWindowTitle("%s%s — %s" % (nombre, " •" if self.dirty and hay else "", APP_NAME))

    def _show_zoom(self, z: float):
        self.lbl_zoom.setText("%d %%" % round(z * 100))

    # -- proyecto ---------------------------------------------------------- #
    def project_data(self, destino: str) -> dict:
        base = os.path.dirname(os.path.abspath(destino))
        paginas = []
        for p in self.pages:
            try:
                # con / siempre: el proyecto vale en Windows y en Mac
                rel = Path(os.path.relpath(p["path"], base)).as_posix()
            except ValueError:                  # otra unidad, en Windows
                rel = None
            paginas.append({"path": p["path"], "rel": rel, "size": p.get("size"),
                            "draw": p["draw"]})
        return {"app": APP_NAME, "version": 1, "pages": paginas}

    def adopt_pasted(self, destino: str):
        """Las imagenes pegadas se copian junto al proyecto, en «<nombre> images»,
        para que el proyecto no dependa de la carpeta de datos de este ordenador."""
        carpeta = Path(destino).with_name(Path(destino).stem + " images")
        cambio = False
        for p in self.pages:
            if not (is_pasted(p["path"]) and os.path.exists(p["path"])):
                continue
            carpeta.mkdir(exist_ok=True)
            nueva = carpeta / Path(p["path"]).name
            if not nueva.exists():
                shutil.copy2(p["path"], nueva)
            if p["path"] in self.thumbs:
                self.thumbs[str(nueva)] = self.thumbs[p["path"]]
            if self._img_cache[0] == p["path"]:
                self._img_cache = (str(nueva), self._img_cache[1])
            p["path"] = str(nueva)
            cambio = True
        if cambio:
            for i, p in enumerate(self.pages):
                self._refresh_item(self.list.item(i), p, i)

    def save_project(self) -> bool:
        if not self.project_path:
            return self.save_project_as()
        try:
            self.adopt_pasted(self.project_path)
            datos = self.project_data(self.project_path)
            tmp = self.project_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.project_path)
        except OSError as e:
            QMessageBox.warning(self, "Save project", "Could not save:\n%s" % e)
            return False
        self._mark_dirty(False)
        self.statusBar().showMessage("Saved %s" % self.project_path, 4000)
        return True

    def save_project_as(self) -> bool:
        inicio = self.project_path or os.path.join(self.ajustes.value("dirs/project", "")
                                                   or self.ajustes.value("dirs/images", ""),
                                                   "Review" + PROJECT_EXT)
        ruta, _ = QFileDialog.getSaveFileName(self, "Save project", inicio,
                                              "DriloReview project (*%s)" % PROJECT_EXT)
        if ruta.lower().endswith(PROJECT_EXTS[1:]):     # el viejo se guarda con el nombre nuevo
            ruta = os.path.splitext(ruta)[0]
        if not ruta:
            return False
        if not ruta.lower().endswith(PROJECT_EXT):
            ruta += PROJECT_EXT
        self.project_path = ruta
        self.ajustes.setValue("dirs/project", os.path.dirname(ruta))
        return self.save_project()

    def open_project_dialog(self):
        if not self.maybe_save():
            return
        ruta, _ = QFileDialog.getOpenFileName(self, "Open project",
                                              self.ajustes.value("dirs/project", ""),
                                              PROJECT_FILTER)
        if ruta:
            self.load_project(ruta)

    def load_project(self, ruta: str) -> bool:
        try:
            with open(ruta, encoding="utf-8") as f:
                datos = json.load(f)
            base = os.path.dirname(os.path.abspath(ruta))
            paginas = []
            for d in datos.get("pages", []):
                path = d.get("path") or ""
                if not os.path.exists(path) and d.get("rel"):
                    rel = d["rel"].replace("\\", "/")   # guardado en Windows
                    alt = os.path.normpath(os.path.join(base, *rel.split("/")))
                    if os.path.exists(alt):     # el proyecto viajo junto a sus imagenes
                        path = alt
                paginas.append({"id": uuid.uuid4().hex, "path": path,
                                "draw": with_ids(list(d.get("draw") or [])),
                                "size": d.get("size")})
        except (OSError, ValueError, TypeError, AttributeError) as e:
            QMessageBox.warning(self, "Open project", "Could not open %s:\n%s" % (ruta, e))
            return False
        self.pages = paginas
        self.current = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.project_path = ruta
        self.ajustes.setValue("dirs/project", os.path.dirname(ruta))
        self._mark_dirty(False)
        self._rebuild_list()
        faltan = sum(1 for p in paginas if not os.path.exists(p["path"]))
        if faltan:
            QMessageBox.information(self, "Open project",
                                    "%d image%s could not be found where the project says. "
                                    "Their drawings are kept." % (faltan, "" if faltan == 1
                                                                  else "s"))
        return True

    def new_project(self):
        if not self.maybe_save():
            return
        self.pages = []
        self.current = None
        self.project_path = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._mark_dirty(False)
        self._rebuild_list()

    def maybe_save(self) -> bool:
        """Antes de perder el trabajo: guardar, descartar o cancelar."""
        if not self.dirty or not self.pages:
            return True
        r = QMessageBox.question(
            self, APP_NAME, "Save the drawings in a project before closing them?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if r == QMessageBox.StandardButton.Save:
            return self.save_project()
        return r == QMessageBox.StandardButton.Discard

    # -- exportar ---------------------------------------------------------- #
    def export_dialog(self):
        if not self.pages:
            return
        dlg = ExportDialog(self, len(self.pages), self.ajustes)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        opciones = dlg.options()
        nombre = (Path(self.project_path).stem if self.project_path
                  else Path(self.pages[0]["path"]).parent.name or "DriloReview")
        carpeta = self.ajustes.value("dirs/pdf", "") or os.path.dirname(self.pages[0]["path"])
        ruta, _ = QFileDialog.getSaveFileName(self, "Export PDF",
                                              os.path.join(carpeta, nombre + ".pdf"),
                                              "PDF (*.pdf)")
        if not ruta:
            return
        if not ruta.lower().endswith(".pdf"):
            ruta += ".pdf"
        self.ajustes.setValue("dirs/pdf", os.path.dirname(ruta))
        prog = QProgressDialog("Writing the PDF…", "Cancel", 0, len(self.pages), self)
        prog.setWindowTitle("Export PDF")
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(300)

        def avance(i):
            prog.setValue(i)
            QApplication.processEvents()
            return not prog.wasCanceled()

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            n = export_pdf(self.pages, ruta, progreso=avance, **opciones)
        except OSError as e:
            n = -1
            error = str(e)
        finally:
            QApplication.restoreOverrideCursor()
            prog.setValue(len(self.pages))
        if n < 0:
            QMessageBox.warning(self, "Export PDF", "Could not write the PDF:\n%s" % error)
        elif n == 0:
            self.statusBar().showMessage("Export cancelled.", 4000)
        else:
            self.statusBar().showMessage("Exported %d pages to %s" % (n, ruta), 8000)
            r = QMessageBox.information(self, "Export PDF",
                                        "Done: %d page%s.\n%s" % (n, "" if n == 1 else "s", ruta),
                                        QMessageBox.StandardButton.Open
                                        | QMessageBox.StandardButton.Ok,
                                        QMessageBox.StandardButton.Ok)
            if r == QMessageBox.StandardButton.Open:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl.fromLocalFile(ruta))

    # -- arrastrar sobre la ventana ---------------------------------------- #
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        rutas = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if rutas:
            e.acceptProposedAction()
            self.add_paths(rutas)

    # -- ayuda ------------------------------------------------------------- #
    def show_help(self):
        QMessageBox.information(self, "How it works", HELP_TEXT % {
            "undo": keys_text("Ctrl+Z"), "redo": keys_text("Ctrl+Shift+Z"),
            "open": keys_text("Ctrl+O"), "export": keys_text("Ctrl+E"),
            "copy": keys_text("Ctrl+C"), "paste": keys_text("Ctrl+V"),
            "dup": keys_text("Ctrl+D"), "fwd": keys_text("Ctrl+]"),
            "back": keys_text("Ctrl+["), "fwd2": keys_text("Ctrl+Shift+↑"),
            "back2": keys_text("Ctrl+Shift+↓")})

    def show_about(self):
        QMessageBox.about(self, "About %s" % APP_NAME,
                          "<b>%s %s</b><br>by %s<br><br>Draw over images and export them "
                          "as one PDF. The annotation tools of DriloBoard, on their own."
                          "<br>Your image files are never modified.<br><br>"
                          "<a href='https://github.com/Cokedrilo/DriloReview'>"
                          "github.com/Cokedrilo/DriloReview</a> · MIT licence"
                          % (APP_NAME, VERSION, APP_AUTHOR))

    def closeEvent(self, e):
        if not self.maybe_save():
            e.ignore()
            return
        self.ajustes.setValue("window/geometry", self.saveGeometry())
        self.pool.clear()
        self.pool.waitForDone(2000)
        super().closeEvent(e)


class App(QApplication):
    """Recoge las imagenes soltadas sobre el icono del Dock (macOS)."""

    def __init__(self, argv):
        super().__init__(argv)
        self.window: MainWindow | None = None
        self._pendientes: list = []

    def event(self, e):
        if e.type() == QEvent.Type.FileOpen:
            ruta = e.file()
            if ruta:
                self._pendientes.append(ruta)
                QTimer.singleShot(100, self._abrir_pendientes)   # llegan de una en una
            return True
        return super().event(e)

    def _abrir_pendientes(self):
        if self.window is None or not self._pendientes:
            return
        rutas, self._pendientes = self._pendientes, []
        self.window.add_paths(rutas)


def selftest() -> int:
    """Arranca la ventana sin mostrarla y escribe un PDF de dos paginas."""
    import tempfile
    fallos = []
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["DRILOREVIEW_DATA"] = tmp
        rutas = []
        for i, (w, h) in enumerate(((640, 480), (300, 500))):
            img = QImage(w, h, QImage.Format.Format_RGB32)
            img.fill(QColor(DRAW_COLORS[i][1]))
            rutas.append(os.path.join(tmp, "img%d.png" % i))
            img.save(rutas[-1])
        win = MainWindow()
        win.add_paths(rutas)
        win.pool.waitForDone(5000)
        if len(win.pages) != 2:
            fallos.append("pages: %d" % len(win.pages))
        win.pages[0]["draw"] = [{"tipo": "flecha", "puntos": [[10, 10], [300, 200]],
                                 "color": "#e81123", "grosor": 6, "alpha": 255}]
        pdf = os.path.join(tmp, "out.pdf")
        if export_pdf(win.pages, pdf) != 2 or os.path.getsize(pdf) < 2000:
            fallos.append("pdf")
        win.dirty = False
        win.close()
    for f in fallos:
        print("selftest:", f)
    print("selftest:", "FAILED" if fallos else "ok")
    return 1 if fallos else 0


def main():
    if WINDOWS:
        try:                                # si no, la barra de tareas pone el de Python
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "cokedrilo.%s.%s" % (APP_NAME, VERSION))
        except (AttributeError, OSError):
            pass
    if "--selftest" in sys.argv:            # que la prueba no deje rastro en los ajustes
        import tempfile
        os.environ.setdefault("DRILOREVIEW_DATA", tempfile.mkdtemp(prefix="driloreview-"))
    app = App(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setWindowIcon(app_icon())
    ajustes = app_settings()
    apply_theme(ajustes.value("theme") or system_theme())
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    win = MainWindow()
    app.window = win
    win.show()
    args = [os.path.abspath(a) for a in sys.argv[1:] if not a.startswith("-")]
    app._pendientes = args + app._pendientes
    QTimer.singleShot(0, app._abrir_pendientes)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
