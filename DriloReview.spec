# -*- mode: python ; coding: utf-8 -*-
"""Receta de empaquetado de DriloReview.

Lo normal es no llamarla a mano sino con build.py, que hace todo:
    Windows:  build_windows.bat     macOS:  ./build_macos.sh

Solo usa QtCore, QtGui (donde esta QPdfWriter) y QtWidgets: el resto de Qt
se deja fuera para que el paquete pese poco.
"""
import os
import re
import subprocess
import sys

MAC = sys.platform == "darwin"
_CODIGO = open("driloreview.py", encoding="utf-8").read()
VERSION = re.search(r'^VERSION = "([^"]+)"', _CODIGO, re.M).group(1)
AUTOR = re.search(r'^APP_AUTHOR = "([^"]+)"', _CODIGO, re.M).group(1)
COPYRIGHT = "© 2026 %s · MIT licence" % AUTOR

# Windows: lo que sale en Propiedades > Detalles del .exe
VERSION_WIN = None
if not MAC:
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo,
                                                     StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)
    _n = tuple((int(x) for x in (VERSION.split(".") + ["0", "0", "0"])[:4]))
    VERSION_WIN = VSVersionInfo(
        ffi=FixedFileInfo(filevers=_n, prodvers=_n),
        kids=[StringFileInfo([StringTable("040904B0", [
                  StringStruct("CompanyName", AUTOR),
                  StringStruct("FileDescription", "DriloReview - draw over images, export a PDF"),
                  StringStruct("FileVersion", VERSION),
                  StringStruct("InternalName", "DriloReview"),
                  StringStruct("LegalCopyright", COPYRIGHT),
                  StringStruct("OriginalFilename", "DriloReview.exe"),
                  StringStruct("ProductName", "DriloReview"),
                  StringStruct("ProductVersion", VERSION)])]),
              VarFileInfo([VarStruct("Translation", [0x0409, 1200])])])

# el icono lo genera make_icns.py desde el propio codigo (build.py ya lo hace)
ICONO = os.path.join("build", "DriloReview.icns" if MAC else "DriloReview.ico")
if not os.path.exists(ICONO):
    subprocess.run([sys.executable, "make_icns.py"] + ([] if MAC else ["--ico"]) + [ICONO],
                   check=True)

EXCLUIR = [
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.Qt3DCore",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtSerialPort", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtTextToSpeech", "PySide6.QtUiTools", "PySide6.QtSvgWidgets",
    "numpy", "tkinter", "unittest", "pydoc", "doctest", "email", "http", "xml", "pdb",
]

a = Analysis(
    ["driloreview.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUIR,
    noarchive=False,
    optimize=0,
)

SOBRAN = ("qtvirtualkeyboardplugin", "Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6VirtualKeyboard",
          "Qt6Network", "Qt6OpenGL", "Qt6Multimedia", "plugins/tls/",
          "plugins/networkinformation/", "plugins/multimedia/")
if MAC:
    SOBRAN += ("libqtvirtualkeyboardplugin", "QtQuick.framework", "QtQml.framework",
               "QtQmlModels.framework", "QtQmlMeta.framework", "QtQmlWorkerScript.framework",
               "QtPdf.framework", "QtVirtualKeyboard.framework", "QtNetwork.framework",
               "QtOpenGL.framework", "QtMultimedia.framework")


def sobra(entrada) -> bool:
    return any(s.lower() in str(parte).replace("\\", "/").lower()
               for s in SOBRAN for parte in entrada[:2])


a.binaries = [b for b in a.binaries if not sobra(b)]
a.datas = [d for d in a.datas if not sobra(d)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DriloReview",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,        # el Dock lo recoge la propia app (QFileOpenEvent)
    target_arch=os.environ.get("DRILOREVIEW_ARCH") or None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICONO,
    version=VERSION_WIN,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, upx_exclude=[],
               name="DriloReview")

if MAC:
    app = BUNDLE(
        coll,
        name="DriloReview.app",
        icon=ICONO,
        bundle_identifier="io.github.cokedrilo.driloreview",
        version=VERSION,
        info_plist={
            "CFBundleName": "DriloReview",
            "CFBundleDisplayName": "DriloReview",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSApplicationCategoryType": "public.app-category.education",
            "LSMinimumSystemVersion": "13.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "NSHumanReadableCopyright": COPYRIGHT,
            "CFBundleDocumentTypes": [
                {"CFBundleTypeName": "Image", "CFBundleTypeRole": "Viewer",
                 "LSHandlerRank": "Alternate",
                 "LSItemContentTypes": ["public.image"]},
                {"CFBundleTypeName": "Folder", "CFBundleTypeRole": "Viewer",
                 "LSHandlerRank": "Alternate",
                 "LSItemContentTypes": ["public.folder"]},
            ],
            "NSDesktopFolderUsageDescription":
                "DriloReview opens the images you drag onto it. It never modifies them.",
            "NSDocumentsFolderUsageDescription":
                "DriloReview opens the images you drag onto it. It never modifies them.",
            "NSDownloadsFolderUsageDescription":
                "DriloReview opens the images you drag onto it. It never modifies them.",
            "NSRemovableVolumesUsageDescription":
                "DriloReview opens the images you drag onto it. It never modifies them.",
            "NSNetworkVolumesUsageDescription":
                "DriloReview opens the images you drag onto it. It never modifies them.",
        },
    )
