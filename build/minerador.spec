# PyInstaller: pasta Minerador3D/ com o .exe (sem console). Rode via build/build.py.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent
APP, MINE = ROOT / "scripts" / "app", ROOT / "scripts" / "mine"

datas = [(str(APP / "static"), "scripts/app/static"), (str(APP / "blender_scene.py"), "scripts/app"), (str(APP / "blender_blend.py"), "scripts/app"), (str(APP / "blender_painel.py"), "scripts/app"),
         (str(ROOT / "db" / "schema.sql"), "db"), (str(ROOT / "VERSION"), ".")]
binaries = []
hiddenimports = ["server", "costs", "ml", "render", "slice", "video", "texto", "paths", "updater", "tools_installer",
                 "classify", "store_reader", "model_search", "webview.platforms.edgechromium", "webview.platforms.winforms"]
for pkg in ("playwright", "webview"):  # o Playwright leva um driver Node junto; o pywebview, os arquivos do WebView2
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis([str(APP / "desktop.py")], pathex=[str(APP), str(MINE)], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=["tkinter", "pytest", "selenium", "flask", "flask_cors", "pytest_asyncio"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Minerador3D", console=False, icon=str(ROOT / "build" / "minerador.ico"), upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Minerador3D", upx=False)
