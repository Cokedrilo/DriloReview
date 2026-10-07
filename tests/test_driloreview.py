"""Prueba de DriloReview sin abrir ventanas.

    .venv/bin/python tests/test_driloreview.py          (Mac/Linux)
    .venv\\Scripts\\python.exe tests\\test_driloreview.py  (Windows)

Crea imagenes de prueba, las anade, dibuja, borra, deshace, reordena, guarda y
abre el proyecto y exporta el PDF; prueba las capas (seleccionar, mover, ocultar,
reordenar), el portapapeles, y comprueba que los originales no cambian.
"""
import hashlib
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl    # noqa: E402
from PySide6.QtGui import QAction, QKeySequence, QShortcut  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter          # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox     # noqa: E402

app = QApplication(sys.argv)
TMP = Path(tempfile.mkdtemp(prefix="driloreview-test-"))
os.environ["DRILOREVIEW_DATA"] = str(TMP / "datos")   # nunca los ajustes de verdad

import driloreview as dn                                     # noqa: E402

fallos = []


def check(cond, msg):
    if not cond:
        fallos.append(msg)
        print("FALLO:", msg)


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def pdf_pages(path):
    datos = Path(path).read_bytes()
    return len(re.findall(rb"/Type\s*/Page[^s]", datos))


# imagenes de prueba: apaisada, vertical y una en una subcarpeta
img_dir = TMP / "fotos"
(img_dir / "sub").mkdir(parents=True)
for nombre, (w, h), color in (("a.jpg", (1600, 900), "#3388cc"),
                              ("b.png", (600, 1000), "#cc8833"),
                              ("sub/c.jpg", (800, 800), "#33aa55")):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    p = QPainter(img)
    p.fillRect(w // 4, h // 4, w // 2, h // 2, QColor("white"))
    p.end()
    img.save(str(img_dir / nombre))
originales = {p: md5(p) for p in img_dir.rglob("*.*")}

dn.apply_theme("dark")
win = dn.MainWindow()
win.show()
# nada de dialogos modales en la prueba
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard)

# 1. anadir una carpeta: entran las tres, en orden natural, subcarpeta incluida
win.add_paths([str(img_dir)])
app.processEvents()
win.pool.waitForDone(5000)
app.processEvents()
check(len(win.pages) == 3, "deberian entrar 3 imagenes, entran %d" % len(win.pages))
check([Path(p["path"]).name for p in win.pages] == ["a.jpg", "b.png", "c.jpg"],
      "orden: %s" % [Path(p["path"]).name for p in win.pages])
check(win.list.count() == 3, "la tira deberia tener 3 paginas")
check(win.stack.currentIndex() == 1, "el lienzo deberia verse")
check(win.pages[0]["size"] == [1600, 900], "tamano de a.jpg: %s" % win.pages[0]["size"])

# 2. anadir un archivo suelto en una posicion concreta, y algo que no es imagen
(TMP / "nota.txt").write_text("hola")
win.add_paths([str(img_dir / "b.png")], 0)
check(len(win.pages) == 4 and Path(win.pages[0]["path"]).name == "b.png",
      "b.png deberia ir la primera")
win.add_paths([str(TMP / "nota.txt")])
check(len(win.pages) == 4, "un .txt no deberia entrar")
win.undo()                                    # quita la b.png repetida
check(len(win.pages) == 3, "deshacer deberia quitar la pagina anadida")

# 3. dibujar en la primera pagina (a.jpg)
win.list.setCurrentRow(0)
pid = win.current
check(win.page(pid)["path"].endswith("a.jpg"), "la actual deberia ser a.jpg")
cv = win.canvas
for tool in ("trazo", "rotulador", "linea", "flecha", "rect", "elipse"):
    cv.set_tool(tool)
    cv._puntos = [QPointF(100, 100), QPointF(500, 300), QPointF(900, 600)]
    win.on_drawn(cv._forma())
dn.QInputDialog.getMultiLineText = staticmethod(lambda *a, **k: ("Hola\nmundo", True))
cv.set_tool("texto")
cv._puntos = [QPointF(200, 700)]
win.on_drawn(cv._forma())
check(len(win.page(pid)["draw"]) == 7, "deberia haber 7 dibujos, hay %d"
      % len(win.page(pid)["draw"]))
grosor = [f for f in win.page(pid)["draw"] if f["tipo"] == "trazo"][0]["grosor"]
check(abs(grosor - 6 * 1.6) < 0.01, "el grosor deberia escalar con la imagen: %s" % grosor)

# 4. la goma quita el de mas arriba bajo el puntero (el texto en 200,700)
win.on_erase(QPointF(230, 690), 4)
check(len(win.page(pid)["draw"]) == 6 and
      all(f["tipo"] != "texto" for f in win.page(pid)["draw"]), "la goma deberia quitar el texto")
win.on_erase(QPointF(1500, 50), 4)
check(len(win.page(pid)["draw"]) == 6, "la goma en vacio no deberia quitar nada")
win.undo()
check(len(win.page(pid)["draw"]) == 7, "deshacer deberia devolver el texto")
win.redo()
check(len(win.page(pid)["draw"]) == 6, "rehacer deberia volver a quitarlo")

# 5. reordenar: la pagina actual baja una
win.move_current(1)
check(win.pages[1]["id"] == pid, "a.jpg deberia pasar a la segunda")
check(win.list.item(1).data(dn.PAGE_ROLE) == pid, "la tira deberia seguir el orden")

# arrastrar en la tira: la ultima pasa a la primera
ultimo = win.list.item(2).data(dn.PAGE_ROLE)
win.list.insertItem(0, win.list.takeItem(2))
win.list.reordered.emit()
app.processEvents()
check(win.pages[0]["id"] == ultimo, "arrastrar en la tira deberia reordenar las paginas")
check(win.list.item(0).text().startswith("1 · "), "los numeros deberian rehacerse")
win.undo()
check(win.pages[2]["id"] == ultimo, "deshacer deberia devolver el orden")

# 6. guardar y abrir el proyecto
proyecto = TMP / "analisis.driloreview"
win.project_path = str(proyecto)
check(win.save_project(), "guardar deberia funcionar")
check(not win.dirty, "tras guardar no deberia quedar nada pendiente")
dibujos = [list(p["draw"]) for p in win.pages]
win.new_project()
check(not win.pages and win.stack.currentIndex() == 0, "nuevo deberia vaciarlo")
check(win.load_project(str(proyecto)), "abrir deberia funcionar")
check([p["draw"] for p in win.pages] == dibujos, "los dibujos deberian volver iguales")

# el proyecto viaja con sus imagenes: rutas absolutas rotas, relativas buenas
viaje = TMP / "viaje"
shutil.copytree(img_dir, viaje / "fotos")
shutil.copy(proyecto, viaje / "analisis.driloreview")
shutil.move(str(img_dir), str(TMP / "fotos_movidas"))
check(win.load_project(str(viaje / "analisis.driloreview")), "abrir el proyecto movido")
check(all(os.path.exists(p["path"]) for p in win.pages),
      "las imagenes deberian encontrarse por la ruta relativa")
shutil.move(str(TMP / "fotos_movidas"), str(img_dir))
win.load_project(str(proyecto))

# 7. exportar el PDF en los tres formatos
for formato in ("fit", "a4", "letter"):
    destino = TMP / ("salida_%s.pdf" % formato)
    n = dn.export_pdf(win.pages, str(destino), formato=formato, margen_mm=5,
                      pie=formato == "a4")
    check(n == 3, "%s: deberian salir 3 paginas, salen %d" % (formato, n))
    check(destino.exists() and destino.stat().st_size > 5000, "%s: el PDF no se escribio" % formato)
    check(pdf_pages(destino) == 3, "%s: el PDF tiene %d paginas" % (formato, pdf_pages(destino)))
    check(not Path(str(destino) + ".part").exists(), "%s: queda el .part" % formato)

# cancelar no deja nada
destino = TMP / "cancelado.pdf"
n = dn.export_pdf(win.pages, str(destino), progreso=lambda i: i < 1)
check(n == 0 and not destino.exists() and not Path(str(destino) + ".part").exists(),
      "cancelar no deberia dejar PDF")

# una imagen que ya no esta no rompe la exportacion
paginas = win.pages + [{"id": "x", "path": str(TMP / "no_existe.jpg"), "draw": [],
                        "size": None}]
n = dn.export_pdf(paginas, str(TMP / "con_falta.pdf"))
check(n == 4, "con una imagen perdida deberian salir 4 paginas, salen %d" % n)

# 8. capas: seleccionar, mover, ocultar, reordenar, borrar
win.load_project(str(proyecto))
win.list.setCurrentRow(1)                      # a.jpg, con 6 dibujos
p = win.page(win.current)
check(all(f.get("id") for f in p["draw"]), "todos los dibujos deberian tener id")
check(win.layers.count() == 6, "deberia haber 6 capas, hay %d" % win.layers.count())
check(win.layers.item(0).data(dn.SHAPE_ROLE) == p["draw"][-1]["id"],
      "la capa de arriba deberia ser el ultimo dibujo")
win.set_tool(None)
cv = win.canvas
elipse = [f for f in p["draw"] if f["tipo"] == "elipse"][0]
# pinchar dentro de la elipse (no en su borde) la selecciona
check(cv.picker(QPointF(300, 200), 4), "pinchar dentro de la elipse deberia seleccionar algo")
check(win.sel is not None, "deberia quedar algo seleccionado")
win.select_shape(elipse["id"])
check(win.layers.selectedItems() and
      win.layers.selectedItems()[0].data(dn.SHAPE_ROLE) == elipse["id"],
      "la capa de la elipse deberia marcarse en el panel")
# mover: pincharla de verdad y arrastrar
win._move = (win._snapshot(), elipse, False)
pasos = len(win.undo_stack)
for k in range(1, 11):
    win._on_move_by(10 * k, 5 * k)
win._on_move_done()
movida = win.selected_shape()
check(movida["puntos"][0] == [elipse["puntos"][0][0] + 100, elipse["puntos"][0][1] + 50],
      "la elipse deberia moverse 100, 50: %s" % movida["puntos"][0])
check(len(win.undo_stack) == pasos + 1, "un arrastre deberia ser un solo paso de deshacer")
check(elipse["puntos"][0] != movida["puntos"][0], "la original no deberia cambiar en su sitio")
win.undo()
p = win.page(win.current)
check([f for f in p["draw"] if f["id"] == elipse["id"]][0]["puntos"] == elipse["puntos"],
      "deshacer deberia devolverla a su sitio")
win.redo()
# arrastrar en vacio no selecciona nada (mueve la pagina)
check(not cv.picker(QPointF(1550, 880), 4) and win.sel is None,
      "pinchar en vacio deberia soltar la seleccion")
# ocultar desde el panel: clic en el ojo de su fila
from PySide6.QtTest import QTest                                     # noqa: E402
win.select_shape(elipse["id"])
fila = [i for i in range(win.layers.count())
        if win.layers.item(i).data(dn.SHAPE_ROLE) == elipse["id"]][0]
r = win.layers.visualItemRect(win.layers.item(fila))
QTest.mouseClick(win.layers.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                 r.topLeft() + __import__("PySide6.QtCore", fromlist=["QPoint"]).QPoint(10, r.height() // 2))
app.processEvents()
p = win.page(win.current)
oculta = [f for f in p["draw"] if f["id"] == elipse["id"]][0]
check(oculta.get("oculto") is True, "desmarcar la capa deberia ocultarla")
img = QImage(1600, 900, QImage.Format.Format_ARGB32)
img.fill(QColor("white"))
pt = QPainter(img)
dn.paint_shapes(pt, [oculta])
pt.end()
check(img.pixelColor(*[int(v) for v in oculta["puntos"][0]]).name() == "#ffffff"
      and all(img.pixelColor(x, 450).name() == "#ffffff" for x in range(0, 1600, 20)),
      "una capa oculta no deberia pintarse (ni en el PDF)")
check(dn.shape_at([oculta], QPointF(300, 200), 4, True) is None,
      "una capa oculta no deberia poder pincharse")
win.undo()
check(not [f for f in win.page(win.current)["draw"] if f["id"] == elipse["id"]][0].get("oculto"),
      "deshacer deberia volver a mostrarla")
# reordenar: al fondo y al frente
win.select_shape(elipse["id"])
win.restack(-10 ** 6)
check(win.page(win.current)["draw"][0]["id"] == elipse["id"], "al fondo deberia quedar la primera")
win.restack(10 ** 6)
check(win.page(win.current)["draw"][-1]["id"] == elipse["id"], "al frente deberia quedar la ultima")
win.restack(-1)
check(win.page(win.current)["draw"][-2]["id"] == elipse["id"], "bajar una deberia dejarla penultima")
# reordenar arrastrando en el panel: la de abajo del todo arriba
ultima = win.layers.item(win.layers.count() - 1).data(dn.SHAPE_ROLE)
win.layers.insertItem(0, win.layers.takeItem(win.layers.count() - 1))
win.layers.reordered.emit()
app.processEvents()
check(win.page(win.current)["draw"][-1]["id"] == ultima,
      "arrastrar una capa arriba deberia ponerla delante")
# color y borrar
win.select_shape(elipse["id"])
win.set_color(QColor("#16a34a"))
check(win.selected_shape()["color"] == "#16a34a", "elegir color deberia recolorear la seleccion")
check(win.canvas.tool is None, "recolorear no deberia cambiar de herramienta")
n = len(win.page(win.current)["draw"])
win.delete_shape()
check(len(win.page(win.current)["draw"]) == n - 1 and win.sel is None, "Supr deberia borrarla")
win.undo()
# editar un texto con doble clic
dn.QInputDialog.getMultiLineText = staticmethod(lambda *a, **k: ("Texto", True))
win.set_tool("texto")
cv._puntos = [QPointF(1000, 700)]
win.on_drawn(cv._forma())
win.set_tool(None)
dn.QInputDialog.getMultiLineText = staticmethod(lambda *a, **k: ("Cambiado", True))
win._on_edit_at(QPointF(1010, 690), 4)
textos = [f["texto"] for f in win.page(win.current)["draw"] if f["tipo"] == "texto"]
check(textos == ["Cambiado"], "doble clic deberia editar el texto: %s" % textos)
# duplicar, copiar y pegar dibujos
n = len(win.page(win.current)["draw"])
win.duplicate_shape()
check(len(win.page(win.current)["draw"]) == n + 1, "duplicar deberia anadir una copia")
copia = win.selected_shape()
check(copia["texto"] == "Cambiado" and copia["id"] not in
      [f["id"] for f in win.page(win.current)["draw"][:-1]], "la copia deberia tener id nuevo")
win.copy_shape()
win.list.setCurrentRow(0)                      # se pega en otra pagina
antes = len(win.page(win.current)["draw"])
win.paste()
check(len(win.page(win.current)["draw"]) == antes + 1, "pegar deberia anadir el dibujo copiado")
check(len(win.pages) == 3, "pegar un dibujo no deberia anadir paginas")

# 9. portapapeles: una imagen y archivos copiados
captura = QImage(500, 300, QImage.Format.Format_RGB32)
captura.fill(QColor("#aa22aa"))
QApplication.clipboard().setImage(captura)
win.list.setCurrentRow(0)
win.paste()
check(len(win.pages) == 4, "pegar una imagen deberia anadir una pagina")
pegada = win.pages[1]
check(dn.is_pasted(pegada["path"]) and os.path.exists(pegada["path"]),
      "la imagen pegada deberia guardarse en la carpeta de pegadas")
check(win.current == pegada["id"], "la pagina pegada deberia ir detras de la actual y verse")
check(pegada["size"] == [500, 300], "tamano de la pegada: %s" % pegada["size"])
datos = QMimeData()
datos.setUrls([QUrl.fromLocalFile(str(img_dir / "b.png")),
               QUrl.fromLocalFile(str(img_dir / "sub" / "c.jpg"))])
QApplication.clipboard().setMimeData(datos)
win.paste()
check(len(win.pages) == 6, "pegar dos archivos copiados deberia anadir dos paginas")
# al guardar, las pegadas se copian junto al proyecto
proyecto2 = TMP / "con pegadas.driloreview"
win.project_path = str(proyecto2)
check(win.save_project(), "guardar con pegadas")
junto = TMP / "con pegadas images"
check(junto.is_dir() and len(list(junto.glob("*.png"))) == 1,
      "la pegada deberia copiarse a «con pegadas images»")
check(win.pages[1]["path"].startswith(str(junto)), "la pagina deberia apuntar a la copia")
datos_json = __import__("json").loads(proyecto2.read_text(encoding="utf-8"))
check(all("\\" not in (d["rel"] or "") for d in datos_json["pages"]),
      "las rutas relativas deberian ir con /")
# limpieza de pegadas viejas
vieja = dn.pasted_dir() / "pasted-vieja.png"
captura.save(str(vieja))
os.utime(vieja, (0, 0))
dn.prune_pasted(set())
check(not vieja.exists(), "las pegadas de hace mas de 30 dias deberian borrarse")

# 10. un proyecto viejo (sin ids) y guardado en Windows (rutas con \)
win_proj = TMP / "windows.driloreview"
win_proj.write_text(__import__("json").dumps({"app": "DriloReview", "version": 1, "pages": [
    {"path": "C:\\Users\\alguien\\fotos\\a.jpg", "rel": "fotos\\a.jpg", "size": [1600, 900],
     "draw": [{"tipo": "linea", "puntos": [[0, 0], [10, 10]], "color": "#e81123",
               "grosor": 4, "alpha": 255}]}]}), encoding="utf-8")
check(win.load_project(str(win_proj)), "abrir un proyecto hecho en Windows")
check(os.path.exists(win.pages[0]["path"]), "la ruta relativa con \\ deberia encontrarse")
check(win.pages[0]["draw"][0].get("id"), "los dibujos viejos deberian recibir id")

# 11. ningun atajo repetido: Qt no ejecuta los que son ambiguos
atajos = []
for a in win.findChildren(QAction):
    atajos += [k.toString() for k in a.shortcuts() if not k.isEmpty()]
for sc in win.findChildren(QShortcut):
    if not sc.key().isEmpty():
        atajos.append(sc.key().toString())
repetidos = sorted({k for k in atajos if atajos.count(k) > 1})
check(not repetidos, "atajos repetidos: %s" % repetidos)

# 12. opacidad de las capas
win.load_project(str(proyecto))
win.list.setCurrentRow(1)
win.set_tool(None)
p = win.page(win.current)
linea = [f for f in p["draw"] if f["tipo"] == "linea"][0]
win.select_shape(linea["id"])
check(win.sld_opacity.isEnabled() and win.sld_opacity.value() == 100,
      "con una capa seleccionada, el deslizador deberia estar a 100")
pasos = len(win.undo_stack)
sld = win.sld_opacity
sld.setSliderDown(True)                        # arrastrar: se ve al momento...
for v in (80, 60, 40, 30):
    sld.setValue(v)
check(win.selected_shape().get("opacidad") == 30, "arrastrando deberia cambiar la opacidad")
check(len(win.undo_stack) == pasos, "mientras se arrastra no deberia apilar deshacer")
sld.setSliderDown(False)                       # ...y al soltar, un solo paso
check(len(win.undo_stack) == pasos + 1, "un arrastre de opacidad deberia ser un paso")
fila = [win.layers.item(i).text() for i in range(win.layers.count())
        if win.layers.item(i).data(dn.SHAPE_ROLE) == linea["id"]]
check(fila and fila[0].endswith("30 %"), "la capa deberia mostrar su opacidad: %s" % fila)
img = QImage(200, 200, QImage.Format.Format_ARGB32)
for op, esperado in ((100, 255), (30, 77)):
    img.fill(QColor(0, 0, 0, 0))
    pt = QPainter(img)
    dn.paint_shape(pt, {"tipo": "linea", "puntos": [[0, 100], [200, 100]],
                        "color": "#e81123", "grosor": 20, "alpha": 255, "opacidad": op})
    pt.end()
    a_ = img.pixelColor(100, 100).alpha()
    check(abs(a_ - esperado) <= 2, "opacidad %d: alfa %d, esperaba %d" % (op, a_, esperado))
# el rotulador ya es transparente: la opacidad lo multiplica
f = {"tipo": "rotulador", "puntos": [[0, 100], [200, 100]], "color": "#fcd116",
     "grosor": 20, "alpha": 90, "opacidad": 50}
img.fill(QColor(0, 0, 0, 0))
pt = QPainter(img)
dn.paint_shape(pt, f)
pt.end()
check(abs(img.pixelColor(100, 100).alpha() - 45) <= 2, "rotulador al 50 %%: alfa %d"
      % img.pixelColor(100, 100).alpha())
win.undo()
check("opacidad" not in win.selected_shape(), "deshacer deberia devolverla al 100 %")
check(win.sld_opacity.value() == 100, "el deslizador deberia seguir al deshacer")
sld.setValue(50)                               # teclado o clic: un paso directo
check(win.selected_shape().get("opacidad") == 50 and len(win.undo_stack) == pasos + 1,
      "cambiar la opacidad sin arrastrar deberia ser un paso")
win.project_path = str(TMP / "opacidad.driloreview")
win.save_project()
win.load_project(win.project_path)
check(any(f.get("opacidad") == 50 for p in win.pages for f in p["draw"]),
      "la opacidad deberia guardarse en el proyecto")
win.select_shape(None)
check(not win.sld_opacity.isEnabled(), "sin seleccion, el deslizador deberia apagarse")

# 13. escala de la interfaz
base_pt = QApplication.font().pointSizeF()
icono_base = win.tool_buttons["trazo"].iconSize().width()
mini_base = win.list.iconSize().width()
win.set_interface_scale(1.5)
check(abs(QApplication.font().pointSizeF() - base_pt * 1.5) < 0.01,
      "la letra deberia crecer al 150 %%: %s" % QApplication.font().pointSizeF())
check(win.tool_buttons["trazo"].iconSize().width() == round(icono_base * 1.5),
      "los iconos deberian crecer: %d" % win.tool_buttons["trazo"].iconSize().width())
check(win.list.iconSize().width() == round(mini_base * 1.5), "las miniaturas deberian crecer")
check("33px" in QApplication.instance().styleSheet(), "la hoja de estilo deberia escalarse")
pm = win.tool_buttons["trazo"].icon().pixmap(win.tool_buttons["trazo"].iconSize())
check(pm.width() >= round(icono_base * 1.5), "el icono deberia dibujarse al tamano nuevo")
check(win.sld_ui.value() == 150 and win.b_ui_val.text() == "150 %", "el control deberia decir 150 %")
check(float(win.ajustes.value("ui/scale")) == 1.5, "la escala deberia guardarse")
win.sld_ui.setValue(80)                        # con el deslizador (sin arrastrar)
check(dn.UI_SCALE == 0.8, "el deslizador deberia aplicar 80 %%: %s" % dn.UI_SCALE)
win.set_interface_scale(9)
check(dn.UI_SCALE == dn.UI_SCALE_MAX, "la escala deberia tener tope")
win.set_interface_scale(1.0)
check(abs(QApplication.font().pointSizeF() - base_pt) < 0.01, "volver al 100 %")
check(win.tool_buttons["trazo"].iconSize().width() == icono_base, "los iconos deberian volver")

# 14. el tema se cambia sin errores
win.toggle_theme()
win.toggle_theme()

# 9. los originales, intactos
for p, h in originales.items():
    check(md5(p) == h, "se ha modificado %s" % p)

win.dirty = False
win.close()
print("PDF de muestra:", TMP / "salida_fit.pdf")
if fallos:
    print("\n%d fallo(s)" % len(fallos))
    sys.exit(1)
print("todo bien")
