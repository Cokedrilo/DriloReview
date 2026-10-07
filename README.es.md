# DriloReview — dibujar sobre imágenes y sacar un PDF

De Drilo. Código y descargas: <https://github.com/Cokedrilo/DriloReview>
(antes se llamaba DriloNalisis; abre también los proyectos `.drilonalisis`).

La parte de anotar de [DriloBoard](../DriloBoard), convertida en un programa
aparte y mucho más simple: **arrastras o pegas imágenes, dibujas encima,
recolocas lo dibujado y exportas todas juntas como un solo PDF**, una página
por imagen. Funciona en **Windows y macOS** (y en Linux desde el código).

Como DriloBoard, la interfaz está en inglés y **nunca toca tus archivos**: los
dibujos se guardan como objetos (trazos, flechas, texto…) y solo se funden con
la imagen dentro del PDF, donde además van como **vectores**: nítidos aunque
amplíes.

## Arrancar

Las dos versiones se descargan de la página de
[*Releases*](https://github.com/Cokedrilo/DriloReview/releases/latest).

**Windows.** `DriloReview-1.2.0-windows.exe` es **un solo archivo**: sin zip y
sin instalar nada. Se descarga y se abre con doble clic; tarda unos segundos
en arrancar porque se desempaqueta cada vez. Puede ir en un USB y no escribe
en el registro; los ajustes y las imágenes pegadas van a
`%APPDATA%\DriloReview`. La primera vez Windows puede avisar de que el editor
es desconocido: *Más información* → *Ejecutar de todas formas*. Puedes
arrastrar imágenes sobre el `.exe` para abrirlas.

**Mac.** Abre `DriloReview-1.2.0-macos.dmg` y arrastra DriloReview a
Aplicaciones (una sola app para Intel y Apple Silicon, macOS 13 o posterior). La primera vez macOS avisa de que no está
notarizada: clic derecho → *Abrir*, o en Terminal
`xattr -dr com.apple.quarantine /ruta/a/DriloReview.app`. Puedes soltar
imágenes o carpetas **sobre el icono del Dock**. Los ajustes van en
`~/Library/Application Support/DriloReview`.

**Desde el código.** `DriloReview.bat` (Windows) o `./driloreview.sh`
(Mac/Linux). La primera vez crean el entorno e instalan PySide6.

En Mac los atajos con `Ctrl` son con `⌘`.

## Cómo se usa

1. **Añadir imágenes**. Cada imagen es una página.
   - **Arrastrándolas** (o carpetas enteras, con sus subcarpetas) a la
     ventana, o con *Add images* (`Ctrl+O`). Soltadas sobre la **tira de la
     izquierda** entran justo en ese punto; sobre el lienzo, al final.
   - **Pegándolas** con `Ctrl+V` o el botón *Paste*: una captura de pantalla
     (`Win+Mayús+S` en Windows, `⌃⇧⌘4` en Mac), una imagen copiada del navegador o
     de otro programa, o **archivos copiados** en el Explorador / Finder.
     Entran detrás de la página que estás viendo.
   - La tira se **reordena arrastrando**. `Ctrl+↑` / `Ctrl+↓` mueven la página
     actual. `Supr` quita las seleccionadas (clic derecho también).
2. **Dibujar**: *Pen* `P`, *Highlighter* `H`, *Line* `L`, *Arrow* `A`,
   *Rectangle* `R`, *Ellipse* `O`, *Text* `T` (clic y escribes; admite varias
   líneas) y *Eraser* `E`, que borra el dibujo entero sobre el que pinchas.
   - **Mayúsculas** mientras arrastras: líneas y flechas a 45°, cuadrados y
     círculos.
   - Diez colores a un clic y `…` para cualquier otro. El **grosor es
     proporcional a la imagen**: un «6» se ve igual en una foto de 800 px que
     en una de 6000.
3. **Mover lo dibujado** con *Select and move* `V` (la flecha del ratón):
   - **Pincha un dibujo y arrástralo.** Rectángulos y elipses se pueden coger
     también por dentro. Todo el arrastre es un solo paso de deshacer.
   - Pinchar en vacío y arrastrar mueve la página; la rueda hace zoom con
     cualquier herramienta, el botón central arrastra siempre, `0` encaja.
   - Con un dibujo seleccionado: **un clic en un color lo recolorea**,
     **doble clic en un texto lo edita**, `Supr` lo borra, `Esc` lo suelta.
   - `Ctrl+C` / `Ctrl+V` copian y pegan dibujos (también a otra página) y
     `Ctrl+D` duplica.
4. **Capas** (panel de la derecha): cada dibujo de la página es una capa, con
   la herramienta con que se hizo y su color. **La de arriba de la lista es la
   que queda delante.**
   - Clic en una capa la selecciona en el lienzo, y al revés.
   - **Arrastra** las capas para cambiar qué tapa a qué, o usa los botones de
     abajo: subir `Ctrl+]` / `Ctrl+Mayús+↑`, bajar `Ctrl+[` / `Ctrl+Mayús+↓`;
     con `Ctrl+Mayús+]` / `[` van al frente o al fondo del todo.
   - **El ojo** oculta o muestra la capa (`Ctrl+Mayús+H`). Las ocultas no salen
     en la miniatura **ni en el PDF**, pero no se pierden.
   - La papelera, `Supr` o doble clic (en un texto, para editarlo).
5. **Exportar PDF** (`Ctrl+E`):
   - *Page size*: con la forma de cada imagen (sin bordes), o A4 / Carta
     girando cada página según la imagen sea vertical o apaisada.
   - *Image quality*: resolución original o reducida (3000, 1800, 1200 px de
     lado mayor) para que el PDF pese menos. Los dibujos van en vectorial
     siempre.
   - *Margin* y, opcionalmente, número de página y nombre del archivo debajo.
   - Si cancelas a medias, o el PDF anterior está abierto en un visor y no se
     puede sustituir, no queda ningún PDF roto.

`Ctrl+Z` deshace y `Ctrl+Mayús+Z` (o `Ctrl+Y` en Windows) rehace **todo**:
trazos, movimientos, colores, capas, añadir, quitar y reordenar páginas.

## Proyectos

*File → Save project* (`Ctrl+S`) guarda la lista de páginas y sus dibujos
—con sus capas, ocultas incluidas— en un archivo `.driloreview`, para seguir
otro día. Las imágenes no van dentro: se guardan sus rutas, absolutas y
relativas al proyecto, así que si mueves la carpeta con el proyecto y las
imágenes juntos, sigue encontrándolas, **también de Windows a Mac y al
revés**. Si falta alguna, avisa y conserva sus dibujos. Un `.driloreview`
soltado en la ventana se abre. Al cerrar con cambios sin guardar, pregunta.

**Las imágenes pegadas** se guardan al pegarlas en la carpeta de datos
(`pasted/`). Al guardar el proyecto se copian junto a él, en una carpeta
`<nombre del proyecto> images`, para que el proyecto no dependa de este
ordenador. Las pegadas que no llegaron a guardarse en ningún proyecto se
borran solas a los 30 días.

## Pruebas y empaquetado

```
.venv/bin/python tests/test_driloreview.py        (Mac)
.venv\Scripts\python.exe tests\test_driloreview.py   (Windows)
```

Corre sin ventanas y con su propia carpeta de datos. Cubre añadir, dibujar con
cada herramienta, goma, deshacer, reordenar páginas, guardar y abrir (también
el proyecto movido de sitio y uno guardado en Windows), exportar en los tres
formatos, cancelar, una imagen perdida; las capas (seleccionar, mover,
ocultar con el ojo, reordenar, recolorear, editar texto, copiar, duplicar);
pegar una imagen y archivos; que no haya dos atajos iguales; y que los
originales no cambian.

**Empaquetar**: en cada sistema, el suyo.

- Windows: doble clic en `build_windows.bat` →
  `dist\DriloReview-<versión>-windows.exe`, un solo archivo.
- Mac: `./build_macos.sh` → `dist/DriloReview.app` y
  `dist/DriloReview-<versión>-macos.dmg`.

Los dos crean el entorno `.venv` si hace falta y llaman a `build.py`, que
genera el icono (`.ico` o `.icns`) desde el propio código, empaqueta con
`DriloReview.spec`, firma en Mac (ad hoc, o con tu certificado si pones
`CODESIGN_IDENTITY`), arranca la app empaquetada con `--selftest` y deja el
`.exe` o el `.dmg`. PyInstaller no cruza sistemas: la versión de Windows se construye en
Windows.

**Publicar una versión**: sube la versión en `VERSION` (y en los enlaces de
`README.md`), y luego

```
git tag v1.2.0 && git push origin main v1.2.0
```

GitHub Actions (`.github/workflows/release.yml`) construye en Windows y en Mac,
pasa las pruebas en los dos, y crea la *release* con el `.exe` y el `.dmg`. La de Mac
sale universal (Intel y Apple Silicon) porque usa el Python de python.org.

Solo necesita `PySide6-Essentials` (el PDF lo escribe `QPdfWriter`, de
QtGui), por eso pesa unos 21 MB.
