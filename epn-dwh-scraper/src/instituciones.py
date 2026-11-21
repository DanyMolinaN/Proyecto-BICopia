"""
Cargador del registro de instituciones (config/instituciones.yaml o
config/instituciones_ces64.yaml).

Provee acceso tipado al catálogo de IES configuradas, con validación básica
y filtrado por estado de integración.

Cambios rama ies-ces-64 (Fase 1):
  - Nuevos campos opcionales: ces_cod, ces_codp, ces_url, portal_url,
    provincia, canton.  Todos tienen valor por defecto seguro para
    mantener compatibilidad con instituciones.yaml original.
  - InstitucionesRegistry acepta un path explícito; la instancia global
    sigue apuntando a instituciones.yaml para no romper nada.
  - Nuevo método load_ces64() devuelve un registry cargado desde
    instituciones_ces64.yaml.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

_BASE_DIR = Path(__file__).resolve().parent.parent
_INSTITUCIONES_PATH = _BASE_DIR / "config" / "instituciones.yaml"
_INSTITUCIONES_CES64_PATH = _BASE_DIR / "config" / "instituciones_ces64.yaml"


class InstitucionConfig:
    """Representación de una institución del catálogo."""

    def __init__(self, data: Dict[str, Any]) -> None:
        self.id: str = data["id"]
        self.nombre: str = data["nombre"]
        self.sigla: str = data.get("sigla", "")
        self.tipo_institucional: str = data.get("tipo_institucional", "no_determinado")
        self.financiamiento: str = data.get("financiamiento", "no_determinado")
        self.base_url: str = data.get("base_url", "")
        self.endpoints: Dict[str, str] = data.get("endpoints", {})
        self.adaptador: str = data.get("adaptador", "generico")
        self.estado_integracion: str = data.get("estado_integracion", "pendiente")
        self.observaciones: str = data.get("observaciones", "")
        # Campos nuevos CES (Fase 1) — opcionales para compatibilidad hacia atrás
        self.ces_cod: Optional[int] = data.get("ces_cod")
        self.ces_codp: Optional[int] = data.get("ces_codp")
        self.ces_url: str = data.get("ces_url", "")
        self.portal_url: str = data.get("portal_url", "")
        self.provincia: str = data.get("provincia", "")
        self.canton: str = data.get("canton", "")

    def get_endpoint(self, key: str) -> Optional[str]:
        """Devuelve la URL de un endpoint o None si no está configurado."""
        return self.endpoints.get(key)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<InstitucionConfig id={self.id!r} estado={self.estado_integracion!r}>"


class InstitucionesRegistry:
    """Catálogo de IES cargado desde un archivo YAML de instituciones."""

    def __init__(self, path: Path = _INSTITUCIONES_PATH) -> None:
        self._instituciones: Dict[str, InstitucionConfig] = {}
        self._load(path)

    def _load(self, path: Path) -> None:
        if not path.exists():
            raise FileNotFoundError(f"Archivo de registro no encontrado: {path}")
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        for item in raw.get("instituciones", []):
            inst = InstitucionConfig(item)
            self._instituciones[inst.id] = inst

    def get(self, institucion_id: str) -> Optional[InstitucionConfig]:
        """Devuelve la configuración de una institución por ID."""
        return self._instituciones.get(institucion_id)

    def all(self) -> List[InstitucionConfig]:
        """Lista todas las instituciones registradas."""
        return list(self._instituciones.values())

    def habilitadas(self) -> List[InstitucionConfig]:
        """Lista solo las instituciones habilitadas."""
        return [i for i in self._instituciones.values() if i.estado_integracion == "habilitada"]

    def activas(self) -> List[InstitucionConfig]:
        """Lista instituciones habilitadas y piloto."""
        return [
            i for i in self._instituciones.values()
            if i.estado_integracion in ("habilitada", "piloto")
        ]

    def por_tipo(self, tipo: str) -> List[InstitucionConfig]:
        """Lista instituciones por tipo_institucional (ej: 'pública')."""
        return [i for i in self._instituciones.values() if i.tipo_institucional == tipo]


def load_ces64() -> "InstitucionesRegistry":
    """Carga y devuelve el registry con las 64 IES del CES (Fase 1).

    Usa config/instituciones_ces64.yaml. No reemplaza la instancia global
    ``registry`` (que sigue apuntando a instituciones.yaml).
    """
    return InstitucionesRegistry(path=_INSTITUCIONES_CES64_PATH)


# Instancia global accesible — apunta a instituciones.yaml (compatibilidad)
registry = InstitucionesRegistry()
