import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
import proc

SCRIPTS = Path(__file__).parent.parent / "scripts"


def test_nenhum_processo_nasce_fora_do_helper():
    """O exe não tem console: qualquer subprocess direto faz uma janela preta piscar. Todo mundo usa proc.run/proc.popen."""
    rx = re.compile(r"\bsubprocess\b|\bPopen\(|\bos\.system\(|\bos\.startfile\(|\bos\.popen\(")
    bad = [f"{f.relative_to(SCRIPTS)}:{i}" for f in SCRIPTS.rglob("*.py") if f.name != "proc.py"
           for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1) if rx.search(line) and not line.lstrip().startswith("#")]
    assert not bad, "use proc.run/proc.popen em vez de: " + ", ".join(bad)


def test_helper_esconde_a_janela(monkeypatch):
    got = {}
    monkeypatch.setattr(proc.subprocess, "run", lambda *a, **kw: got.update(kw))
    proc.run(["x"])
    assert got["creationflags"] & proc.CREATE_NO_WINDOW
    if sys.platform == "win32":
        assert got["startupinfo"].wShowWindow == proc.subprocess.SW_HIDE
        got.clear()
        proc.run(["x"], show=True)  # Chrome e instalador precisam da janela deles
        assert "startupinfo" not in got and got["creationflags"] & proc.CREATE_NO_WINDOW
