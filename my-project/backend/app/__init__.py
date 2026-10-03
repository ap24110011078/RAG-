"""Enterprise Document Intelligence Chatbot - Backend API."""

import importlib.util
from pathlib import Path

# Provide `app` when imported as `from app import app` in test runners
_app_file = Path(__file__).resolve().parent.parent / "app.py"
if _app_file.exists():
    _spec = importlib.util.spec_from_file_location("app_main", str(_app_file))
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        app = getattr(_mod, "app", None)

