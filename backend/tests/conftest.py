import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _load_dotenv() -> None:
    """Carga el .env de la raiz del proyecto sin pisar variables ya presentes.

    El .env vive dos niveles por encima de backend/tests/ (raiz del repo).
    Se abre con utf-8-sig para tolerar el BOM. Usamos os.environ.setdefault
    para que quien exporte una variable manualmente siga mandando. Parser
    minimo a mano porque python-dotenv no es dependencia del proyecto.
    NUNCA se imprimen los valores cargados.
    """
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


_load_dotenv()
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")
