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


def restored_path(db,path):
    """Resolve a copied workspace without rewriting immutable historical bodies."""
    import json
    row=db.conn.execute("SELECT value FROM meta WHERE key='restore_path_mapping'").fetchone()
    original=Path(path)
    for old,new in sorted((json.loads(row[0]) if row else {}).items(),key=lambda x:-len(x[0])):
        if original.is_relative_to(Path(old)):
            return Path(new)/original.relative_to(Path(old))
    return original
