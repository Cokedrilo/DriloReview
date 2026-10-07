"""Empaqueta DriloReview para el sistema en que se ejecuta (Windows o macOS).

    Windows:  build_windows.bat      macOS:  ./build_macos.sh

(esos dos crean el entorno .venv con PySide6 y PyInstaller y llaman a este).

Genera el icono, empaqueta con DriloReview.spec, firma en macOS, arranca la
app empaquetada con --selftest (sin ventanas) y deja el zip en dist/:
    Windows:  dist/DriloReview-<version>-portable-win64.zip
    macOS:    dist/DriloReview-<version>-macos.zip
"""
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
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

    for viejo in ("build/DriloReview", "dist/DriloReview", "dist/DriloReview.app"):
        shutil.rmtree(viejo, ignore_errors=True)
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
        carpeta = Path("dist/DriloReview")
        exe = carpeta / "DriloReview.exe"

    # que el paquete arranque entero antes de darlo por bueno; lo que falte de
    # Qt se veria aqui y no desde el codigo fuente
    print("== selftest", flush=True)
    with tempfile.TemporaryDirectory() as datos:
        entorno = dict(os.environ, QT_QPA_PLATFORM="offscreen", DRILOREVIEW_DATA=datos)
        r = subprocess.run([str(exe), "--selftest"], env=entorno, timeout=120)
    if r.returncode != 0:
        sys.exit("== el selftest ha fallado (codigo %d)" % r.returncode)

    if MAC:
        zip_ = Path("dist/DriloReview-%s-macos.zip" % VERSION)
        zip_.unlink(missing_ok=True)
        # ditto conserva los enlaces simbolicos de los frameworks y la firma; zip no
        run("ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, zip_)
    else:
        # restos que no se reparten: ajustes o pegadas de alguna ejecucion de prueba
        for resto in ("settings.ini", "pasted"):
            p = carpeta / resto
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
        (carpeta / "Read me - Leeme.txt").write_text(LEEME % {"v": VERSION}, encoding="utf-8")
        zip_ = Path("dist/DriloReview-%s-portable-win64.zip" % VERSION)
        zip_.unlink(missing_ok=True)
        with zipfile.ZipFile(zip_, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(carpeta.rglob("*")):
                z.write(f, Path("DriloReview") / f.relative_to(carpeta))
    print("== listo: %s (%.0f MB)" % (zip_, zip_.stat().st_size / 1e6), flush=True)


LEEME = """DriloReview %(v)s for Windows (portable) - by Drilo
=========================================================

Unzip this folder anywhere (a USB stick too) and run DriloReview.exe. Nothing is
installed. Settings and pasted images are kept in this same folder.

The first time, Windows may warn that the publisher is unknown (the program is not
signed): click "More info" and then "Run anyway".

------------------------------------------------------------------------------

DriloReview %(v)s para Windows (portable) - de Drilo

Descomprime esta carpeta donde quieras (tambien en un USB) y ejecuta
DriloReview.exe. No se instala nada. Los ajustes y las imagenes pegadas se
guardan en esta misma carpeta.

La primera vez Windows puede avisar de que el editor es desconocido (el programa
no esta firmado): pulsa "Mas informacion" y luego "Ejecutar de todas formas".
"""

if __name__ == "__main__":
    main()
