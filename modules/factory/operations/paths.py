"""One workspace/data layout shared by CLI, API, worker and restore."""
from pathlib import Path
from .config import load_config


def data_root(workspace):
    workspace = Path(workspace).resolve()
    configured = load_config(workspace)["values"].get("DATA_ROOT", "data/factory")
    path = Path(configured)
    return path.resolve() if path.is_absolute() else (workspace / path).resolve()


def database_path(workspace):
    return data_root(workspace) / "factory.db"
