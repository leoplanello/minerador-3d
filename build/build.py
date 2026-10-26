"""Build do Minerador 3D: escreve VERSION, gera o ícone, empacota com PyInstaller e, se o Inno Setup estiver instalado, monta o instalador.
Uso: python build/build.py 1.0.0 [--sem-instalador]
Saída: dist/Minerador3D/ (pasta do programa) e dist/Minerador3D-Setup-<versão>.exe com o .sha256 ao lado."""
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"


def find_iscc():
    for c in (os.environ.get("ISCC"), shutil.which("iscc"), r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe", r"C:\Program Files\Inno Setup 6\ISCC.exe",
              os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe")):
        if c and Path(c).is_file():
            return c
    return None


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    version = (args[0] if args else "0.0.0-dev").lstrip("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+(-[\w.]+)?", version):
        sys.exit(f"versão inválida: {version} (use 1.2.3)")
    (ROOT / "VERSION").write_text(version + "\n", encoding="utf-8")
    subprocess.run([sys.executable, str(ROOT / "build" / "make_icon.py")], check=True)
    shutil.rmtree(DIST / "Minerador3D", ignore_errors=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(DIST), "--workpath", str(ROOT / "build" / "work"),
                    str(ROOT / "build" / "minerador.spec")], check=True, cwd=ROOT)
    exe = DIST / "Minerador3D" / "Minerador3D.exe"
    if not exe.is_file():
        sys.exit("o PyInstaller não gerou o Minerador3D.exe")
    print("programa:", exe)
    if "--sem-instalador" in argv:
        return
    iscc = find_iscc()
    if not iscc:
        sys.exit("Inno Setup não encontrado (defina ISCC ou instale o Inno Setup 6); o programa foi gerado em dist/Minerador3D")
    subprocess.run([iscc, f"/DAppVersion={version}", str(ROOT / "build" / "installer.iss")], check=True, cwd=ROOT)
    setup = DIST / f"Minerador3D-Setup-{version}.exe"
    sha = hashlib.sha256(setup.read_bytes()).hexdigest()
    (DIST / (setup.name + ".sha256")).write_text(f"{sha}  {setup.name}\n", encoding="utf-8")
    print("instalador:", setup, sha)


if __name__ == "__main__":
    main(sys.argv[1:])
