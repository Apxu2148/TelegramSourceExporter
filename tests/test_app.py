import ast
from pathlib import Path


def test_app_module_parses():
    source = Path(__file__).resolve().parents[1] / "app.py"

    ast.parse(source.read_text(encoding="utf-8"))