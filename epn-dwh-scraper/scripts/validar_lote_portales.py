#!/usr/bin/env python3
"""
Validador de portales para lotes de instituciones.
Fase 3: portales oficiales (lotes de 10, con revisión del equipo entre lotes).

Criterios de validación:
1. HTTP 200
2. Portada identifica a la institución
3. Dominio coherente (.edu.ec salvo justificación documentada)
4. robots.txt leído y respetado
5. Detección de WordPress (/wp-json/)
6. Detección de secciones: url_noticias, url_autoridades, url_oferta

Resultado: config/portales_validados.csv
"""

import csv
import sys
from pathlib import Path
from typing import Dict, List

_SCRIPT_DIR = Path(__file__).resolve().parent
_BASE_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_BASE_DIR))

from src.scrapers.portal_validator import PortalValidator

_CSV_PATH = _BASE_DIR / "config" / "portales_validados.csv"

# Candidatos descubiertos para el Lote 1 (primeras 10 IES del catálogo + pilotos)
LOTE_1_CANDIDATOS = [
    {
        "institucion_id": "1001",
        "nombre": "ESCUELA POLITÉCNICA NACIONAL",
        "portal_url": "https://www.epn.edu.ec",
        "metodo_descubrimiento": "portal_oficial_historico",
    },
    {
        "institucion_id": "1003",
        "nombre": "ESCUELA SUPERIOR POLITÉCNICA AGROPECUARIA DE MANABÍ MANUEL FÉLIX LÓPEZ - ESPAM MFL",
        "portal_url": "https://www.espam.edu.ec",
        "metodo_descubrimiento": "busqueda_web_oficial",
    },
    {
        "institucion_id": "1002",
        "nombre": "ESCUELA SUPERIOR POLITÉCNICA DE CHIMBORAZO",
        "portal_url": "https://www.espoch.edu.ec",
        "metodo_descubrimiento": "busqueda_web_oficial",
    },
    {
        "institucion_id": "1021",
        "nombre": "ESCUELA SUPERIOR POLITÉCNICA DEL LITORAL (ESPOL)",
        "portal_url": "https://www.espol.edu.ec",
        "metodo_descubrimiento": "busqueda_web_oficial",
    },
    {
        "institucion_id": "1026",
        "nombre": "FACULTAD LATINOAMERICANA DE CIENCIAS SOCIALES, FLACSO",
        "portal_url": "https://www.flacso.edu.ec",
        "metodo_descubrimiento": "busqueda_web_oficial",
    },
    {
        "institucion_id": "1057",
        "nombre": "INSTITUTO DE ALTOS ESTUDIOS NACIONALES - IAEN",
        "portal_url": "https://www.iaen.edu.ec",
        "metodo_descubrimiento": "busqueda_web_oficial",
    },
    {
        "institucion_id": "1018",
        "nombre": "UNIVERSIDAD AGRARIA DEL ECUADOR",
        "portal_url": "http://www.uagraria.edu.ec",
        "metodo_descubrimiento": "busqueda_web_oficial",
    },
    {
        "institucion_id": "1022",
        "nombre": "UNIVERSIDAD ANDINA SIMÓN BOLÍVAR",
        "portal_url": "https://www.uasb.edu.ec",
        "metodo_descubrimiento": "busqueda_web_oficial",
    },
    {
        "institucion_id": "1005",
        "nombre": "UNIVERSIDAD CENTRAL DEL ECUADOR",
        "portal_url": "https://www.uce.edu.ec",
        "metodo_descubrimiento": "busqueda_web_oficial",
    },
    {
        "institucion_id": "1007",
        "nombre": "UNIVERSIDAD DE CUENCA",
        "portal_url": "https://www.ucuenca.edu.ec",
        "metodo_descubrimiento": "busqueda_web_oficial",
    },
    # Pilotos adicionales para la Ola Piloto (EPN, ESPE, USFQ)
    {
        "institucion_id": "1079",
        "nombre": "UNIVERSIDAD DE LAS FUERZAS ARMADAS-ESPE",
        "portal_url": "https://www.espe.edu.ec",
        "metodo_descubrimiento": "portal_piloto_verificado",
    },
    {
        "institucion_id": "1038",
        "nombre": "UNIVERSIDAD SAN FRANCISCO DE QUITO USFQ",
        "portal_url": "https://www.usfq.edu.ec",
        "metodo_descubrimiento": "portal_piloto_verificado",
    },
]


def main():
    validator = PortalValidator()
    print("Iniciando validación de Lote 1 de portales universitarios...")
    resultados = validator.validate_batch(LOTE_1_CANDIDATOS)

    # Cargar registros previos si existen para merge idempotente
    existing = {}
    if _CSV_PATH.exists():
        with open(_CSV_PATH, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[row["institucion_id"]] = row

    for r in resultados:
        existing[r["institucion_id"]] = r

    fieldnames = [
        "institucion_id", "portal_url", "evidencia",
        "fecha_validacion", "robots_permite", "es_wordpress",
        "url_noticias", "url_autoridades", "url_oferta",
        "estado", "motivo",
    ]

    with open(_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for iid in sorted(existing.keys()):
            writer.writerow(existing[iid])

    print(f"\n[OK] Portales validados guardados en: {_CSV_PATH}")
    for r in resultados:
        print(f"  [{r['institucion_id']}] {r['portal_url']:<32} | estado: {r['estado']} | robots: {r['robots_permite']} | wp: {r['es_wordpress']}")


if __name__ == "__main__":
    main()
