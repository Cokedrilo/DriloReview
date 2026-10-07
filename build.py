"""Empaqueta DriloReview para el sistema en que se ejecuta (Windows o macOS).

    Windows:  build_windows.bat      macOS:  ./build_macos.sh

(esos dos crean el entorno .venv con PySide6 y PyInstaller y llaman a este).

Genera el icono, empaqueta con DriloReview.spec, firma en macOS, arranca la
app empaquetada con --selftest (sin ventanas) y deja en dist/ un solo archivo
que se abre con doble clic, sin descomprimir nada:
    Windows:  dist/DriloReview-<version>-windows.exe
    macOS:    dist/DriloReview-<version>-macos.dmg
"""
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
os.chdir(RAIZ)
MAC = sys.platform == "darwin"
WINDOWS = sys.platform == "win32"
VERSION = re.search(r'^VERSION = "([^"]+)"',
                    (RAIZ / "driloreview.py").read_text(encoding="utf-8"), re.M).group(1)


def run(*args, **kw):
    print("$", " ".join(str(a) for a in args), flush=True)
    subprocess.run([str(a) for a in args], check=True, **kw)


def arquitectura_mac() -> str:
    if os.environ.get("DRILOREVIEW_ARCH"):
        return os.environ["DRILOREVIEW_ARCH"]
    base = getattr(sys, "_base_executable", sys.executable)
    try:
        archs = subprocess.run(["lipo", "-archs", base], capture_output=True,
                               text=True).stdout
    except OSError:
        archs = ""
    return "universal2" if "x86_64" in archs and "arm64" in archs else platform.machine()


def main():
    if not (MAC or WINDOWS):
        sys.exit("build.py empaqueta para Windows o macOS; en Linux usa driloreview.sh")
    if MAC:
        os.environ["DRILOREVIEW_ARCH"] = arquitectura_mac()
    print("== DriloReview %s para %s (%s)" % (
        VERSION, "macOS" if MAC else "Windows",
        os.environ.get("DRILOREVIEW_ARCH") or platform.machine()), flush=True)

    for viejo in ("build/DriloReview", "dist/DriloReview", "dist/DriloReview.app", "dist/dmg"):
        shutil.rmtree(viejo, ignore_errors=True)
    for viejo in Path("dist").glob("DriloReview*.*"):
        if viejo.is_file():
            viejo.unlink()
    icono = Path("build") / ("DriloReview.icns" if MAC else "DriloReview.ico")
    if icono.exists():
        icono.unlink()
    run(sys.executable, "make_icns.py", *([] if MAC else ["--ico"]), icono)
    run(sys.executable, "-m", "PyInstaller", "DriloReview.spec", "--noconfirm")

    if MAC:
        app = Path("dist/DriloReview.app")
        run("codesign", "--force", "--deep", "--sign",
            os.environ.get("CODESIGN_IDENTITY") or "-", app)
        run("codesign", "--verify", "--deep", "--strict", app)
        exe = app / "Contents/MacOS/DriloReview"
    else:
        exe = Path("dist/DriloReview.exe")

    # que el paquete arranque entero antes de darlo por bueno; lo que falte de
    # Qt se veria aqui y no desde el codigo fuente
    print("== selftest", flush=True)
    with tempfile.TemporaryDirectory() as datos:
        entorno = dict(os.environ, QT_QPA_PLATFORM="offscreen", DRILOREVIEW_DATA=datos)
        r = subprocess.run([str(exe), "--selftest"], env=entorno, timeout=120)
    if r.returncode != 0:
        sys.exit("== el selftest ha fallado (codigo %d)" % r.returncode)

    if MAC:
        # el .dmg de siempre: al abrirlo sale la app y un acceso a Aplicaciones
        salida = Path("dist/DriloReview-%s-macos.dmg" % VERSION)
        carpeta = Path("dist/dmg")
        carpeta.mkdir()
        run("ditto", app, carpeta / "DriloReview.app")
        (carpeta / "Applications").symlink_to("/Applications")
        run("hdiutil", "create", "-volname", "DriloReview", "-srcfolder", carpeta,
            "-ov", "-format", "UDZO", salida)
        shutil.rmtree(carpeta)
    else:
        salida = Path("dist/DriloReview-%s-windows.exe" % VERSION)
        shutil.copy2(exe, salida)
    print("== listo: %s (%.0f MB)" % (salida, salida.stat().st_size / 1e6), flush=True)


if __name__ == "__main__":
    main()
