#!/usr/bin/env python3
"""Regenera el inventario de secciones fuente que faltan o requieren validación.

Las fuentes oficiales localizadas pero aún no validadas en extracción se conservan
en la salida con tipo_pendiente=VALIDAR_FUENTE_O_EXTRACCION. Las instituciones y
los códigos CES se toman de la matriz vigente; no se reordenan ni se infieren.
"""

import csv
import re
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
MATRIX = BASE_DIR / "config" / "matriz_fuentes_ies.csv"
OUTPUT = BASE_DIR / "docs" / "secciones_fuentes_pendientes.csv"
HITO2_DIR = BASE_DIR / "data" / "raw" / "hito2"

SECTIONS = [
    ("oferta", "Oferta académica/carreras (P1)", "url_oferta", "estado_oferta"),
    ("autoridades", "Autoridades/rectorado (P2)", "url_autoridades", "estado_autoridades"),
    ("facultades", "Facultades/decanos (P2)", "url_facultades", "estado_facultades"),
    ("docentes", "Personal docente (complementario)", "url_docentes", "estado_docentes"),
    ("noticias", "Noticias institucionales 2024–2025 (P3)", "url_noticias", "estado_noticias"),
]

REVIEW_MARKERS = (
    "pendiente", "candidata", "parcial", "http 403", "http 404", "http 500",
    "http 502", "error", "bloqueada", "revisar", "validar", "falta", "localizar",
    "no se confirmó", "no se confirmo", "no se localizó", "no se localizo",
    "portada sola", "página principal", "pagina principal", "js", "javascript",
    "reintentar", "pdf oficial", "oficial aportada", "extracción por", "extraccion por",
    "temporal",
)


def actual_urls(value):
    return [
        item.strip()
        for item in re.split(r"[;\n]+", value or "")
        if item.strip().lower().startswith("https://")
    ]


def latest_coverage():
    """Lee el inventario de cobertura de la corrida Hito 2 más reciente, si existe."""
    files = list(HITO2_DIR.glob("*/cobertura_extraccion.csv"))
    if not files:
        return "", {}
    path = max(files, key=lambda item: item.stat().st_mtime)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    coverage = {
        (row.get("institucion_id", ""), row.get("modulo", "")): row
        for row in rows
    }
    return path.parent.name, coverage


def main():
    with MATRIX.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    latest_run_id, coverage = latest_coverage()
    pending = []
    for row in rows:
        for _, label, url_field, state_field in SECTIONS:
            urls = actual_urls(row.get(url_field, ""))
            state = (row.get(state_field) or "").strip()
            state_norm = state.casefold()
            latest = coverage.get((row.get("ces_cod", ""), url_field.removeprefix("url_")), {})
            runtime_state = (latest.get("estado_extraccion") or "").strip()
            runtime_url = (latest.get("url_fuente") or "").strip()
            runtime_message = (latest.get("mensaje") or "").strip()
            runtime_review = bool(runtime_state and (
                runtime_state != "ok" or latest.get("limite_paginas_alcanzado", "").casefold() == "true"
            ))
            no_source = not urls
            needs_review = no_source or runtime_review or any(marker in state_norm for marker in REVIEW_MARKERS)
            if not needs_review:
                continue
            if no_source and runtime_url:
                pending_type = "FUENTE_DESCUBIERTA_POR_SCRAPER; revisar y agregar a matriz"
            elif no_source:
                pending_type = "SIN_FUENTE"
            elif runtime_review or any(marker in state_norm for marker in REVIEW_MARKERS):
                pending_type = "VALIDAR_FUENTE_O_EXTRACCION"
            else:
                pending_type = "SIN_FUENTE"
            pending.append({
                "ces_cod": row.get("ces_cod", ""),
                "nombre_ies": row.get("nombre", ""),
                "portal_oficial": row.get("portal_url", ""),
                "seccion_pendiente": label,
                "campo_matriz": url_field,
                "url_actual": "; ".join(urls),
                "url_fuente_reciente": runtime_url,
                "estado_actual": state,
                "run_id_reciente": latest_run_id,
                "estado_extraccion_reciente": runtime_state,
                "registros_extraidos_recientes": latest.get("registros_extraidos", ""),
                "mensaje_extraccion_reciente": runtime_message,
                "tipo_pendiente": pending_type,
            })

    pending.sort(key=lambda row: (int(row["ces_cod"]), row["seccion_pendiente"]))
    fields = [
        "ces_cod", "nombre_ies", "portal_oficial", "seccion_pendiente",
        "campo_matriz", "url_actual", "url_fuente_reciente", "estado_actual",
        "run_id_reciente", "estado_extraccion_reciente", "registros_extraidos_recientes",
        "mensaje_extraccion_reciente", "tipo_pendiente",
    ]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(pending)

    counts = {}
    for item in pending:
        counts[item["seccion_pendiente"]] = counts.get(item["seccion_pendiente"], 0) + 1
    print(f"Secciones con fuente faltante o por validar: {len(pending)}")
    for label, count in counts.items():
        print(f"{label}: {count}")
    print(f"Archivo actualizado: {OUTPUT}")


if __name__ == "__main__":
    main()
