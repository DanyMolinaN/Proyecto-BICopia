#!/usr/bin/env python3
"""
Script reproducible: actualiza instituciones_ces64.yaml a partir de portales_validados.csv.

Uso:
    python scripts/actualizar_yaml_desde_csv.py [--dry-run]

Comportamiento:
  - Lee config/portales_validados.csv.
  - Para cada fila con estado='validado', actualiza en instituciones_ces64.yaml:
      portal_url, estado_integracion (-> 'portal_validado'), endpoints (si no vacíos).
  - Solo escribe si hay cambios efectivos.
  - --dry-run: imprime diferencias sin escribir.
  - Nunca elimina campos existentes; solo agrega/sobreescribe los relacionados al portal.
  - La EPN (id=1001) solo se actualiza si aparece explícitamente en el CSV.

Garantía: el YAML resultante pasa la misma validación de integridad que la Fase 1.
"""

import argparse
import csv
import sys
from pathlib import Path

import yaml

_SCRIPT_DIR = Path(__file__).resolve().parent
_BASE_DIR = _SCRIPT_DIR.parent
_PORTALES_CSV = _BASE_DIR / "config" / "portales_validados.csv"
_YAML_PATH = _BASE_DIR / "config" / "instituciones_ces64.yaml"


def _load_portales() -> dict:
    """Carga portales_validados.csv como {institucion_id: row}."""
    if not _PORTALES_CSV.exists():
        print(f"ERROR: {_PORTALES_CSV} no existe. Ejecuta primero la Fase 3.", file=sys.stderr)
        sys.exit(1)
    portales = {}
    with open(_PORTALES_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            portales[row["institucion_id"]] = row
    return portales


def _load_yaml() -> dict:
    if not _YAML_PATH.exists():
        print(f"ERROR: {_YAML_PATH} no existe.", file=sys.stderr)
        sys.exit(1)
    with open(_YAML_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _apply_updates(data: dict, portales: dict, dry_run: bool) -> int:
    """Aplica actualizaciones del CSV al YAML. Devuelve el número de IES actualizadas."""
    updated = 0
    for inst in data.get("instituciones", []):
        iid = inst["id"]
        portal = portales.get(iid)
        if not portal:
            continue
        if portal.get("estado", "") != "validado":
            continue

        changes = {}

        # portal_url
        new_url = portal.get("portal_url", "").strip()
        if new_url and inst.get("portal_url", "") != new_url:
            changes["portal_url"] = new_url
            changes["base_url"] = new_url

        # estado_integracion
        if inst.get("estado_integracion") in ("pendiente",):
            changes["estado_integracion"] = "portal_validado"

        # adaptador
        if portal.get("es_wordpress") == "si" and inst.get("adaptador") == "pendiente":
            changes["adaptador"] = "wordpress"

        # endpoints
        endpoints = dict(inst.get("endpoints") or {})
        for key, csv_key in [
            ("noticias_web", "url_noticias"),
            ("autoridades", "url_autoridades"),
            ("oferta_grado", "url_oferta"),
        ]:
            val = portal.get(csv_key, "").strip()
            if val and endpoints.get(key, "") != val:
                endpoints[key] = val

        if new_url:
            endpoints.setdefault("robots_txt", new_url.rstrip("/") + "/robots.txt")
            if portal.get("es_wordpress") == "si":
                endpoints.setdefault("noticias_api", new_url.rstrip("/") + "/wp-json/wp/v2/posts")
                endpoints.setdefault("wp_categories", new_url.rstrip("/") + "/wp-json/wp/v2/categories")

        if endpoints != (inst.get("endpoints") or {}):
            changes["endpoints"] = endpoints

        if not changes:
            continue

        if dry_run:
            print(f"[DRY RUN] {iid} ({inst['nombre'][:50]}): {list(changes.keys())}")
        else:
            inst.update(changes)
            print(f"[OK] Actualizado {iid} ({inst['nombre'][:50]}): {list(changes.keys())}")

        updated += 1

    return updated


def main():
    parser = argparse.ArgumentParser(description="Actualiza instituciones_ces64.yaml desde portales_validados.csv")
    parser.add_argument("--dry-run", action="store_true", help="Solo imprime diferencias sin escribir")
    args = parser.parse_args()

    portales = _load_portales()
    data = _load_yaml()

    n = _apply_updates(data, portales, args.dry_run)

    if n == 0:
        print("Sin cambios pendientes.")
        return

    if args.dry_run:
        print(f"\n[DRY RUN] {n} instituciones serían actualizadas. Ejecuta sin --dry-run para aplicar.")
        return

    # Validación de integridad antes de escribir
    insts = data.get("instituciones", [])
    ids = [i["id"] for i in insts]
    assert len(ids) == 64, f"ERROR: el YAML tiene {len(ids)} IES, se esperan 64"
    assert len(ids) == len(set(ids)), "ERROR: hay IDs duplicados"

    with open(_YAML_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    print(f"\n[OK] {_YAML_PATH.name} actualizado. {n} instituciones modificadas.")
    print("Validación de integridad: 64 IES, sin duplicados.")


if __name__ == "__main__":
    main()
