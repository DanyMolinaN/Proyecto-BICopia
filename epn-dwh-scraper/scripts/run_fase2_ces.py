"""
Script para ejecutar la Fase 2 (Fichas institucionales CES para las 64 IES).

Ejecuta CesPerfilScraper una sola vez sobre las 64 IES con caché y 1 s de pausa,
guarda los registros en staging (stg_ies_ces) y en data/interim/ces_64_fichas.csv,
y genera el reporte tabular solicitado por el usuario.
"""

import csv
import json
import time
from pathlib import Path

from src.scrapers.ces_perfil_scraper import CesPerfilScraper
from src.utils.http_client import HttpClient
from src.load.to_staging import StagingLoader

def main():
    print("Iniciando extracción de 64 fichas institucionales del CES...")
    http_client = HttpClient(use_cache=True, institucion_id="CES")
    scraper = CesPerfilScraper(http_client=http_client)
    
    start_t = time.time()
    records = scraper.extract()
    elapsed = time.time() - start_t
    print(f"Extracción completada en {elapsed:.1f} s. Registros obtenidos: {len(records)}")

    # Guardar en staging
    stg = StagingLoader()
    # Asegurar DDL
    ddl_path = Path("sql/stg/stg_ies_ces.sql")
    if ddl_path.exists():
        stg.execute_sql_file(ddl_path)
    inserted = stg.load_raw_table(records, "stg_ies_ces")
    print(f"Registros insertados en stg_ies_ces: {inserted}")

    # Guardar en data/interim/ces_64_fichas.csv
    out_csv = Path("data/interim/ces_64_fichas.csv")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    if records:
        keys = list(records[0].keys())
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            w.writerows(records)
        print(f"Archivo guardado en {out_csv}")

    # Análisis de resultados
    ok_count = sum(1 for r in records if r.get("estado_extraccion") == "ok")
    parcial_count = sum(1 for r in records if r.get("estado_extraccion") == "parcial")
    error_count = sum(1 for r in records if "error" in str(r.get("estado_extraccion", "")))
    coinciden = sum(1 for r in records if not r.get("discrepancia_nombre") and r.get("estado_extraccion") == "ok")
    discrepan = sum(1 for r in records if r.get("discrepancia_nombre"))
    rectores_encontrados = sum(1 for r in records if r.get("rector_nombre"))

    print("\n" + "=" * 80)
    print("RESUMEN FASE 2: FICHAS INSTITUCIONALES CES (64 IES)")
    print("=" * 80)
    print(f"Total IES procesadas         : {len(records)}")
    print(f"Estado 'ok'                  : {ok_count}")
    print(f"Estado 'parcial'             : {parcial_count}")
    print(f"Estado 'error'               : {error_count}")
    print(f"Coincidencia exacta de nombre: {coinciden}")
    print(f"Discrepancia de nombre       : {discrepan}")
    print(f"Rectores/as identificados    : {rectores_encontrados}")
    print("=" * 80)

    # Imprimir muestra tabular
    print(f"\n{'ID':<5} {'Siglas':<8} {'Estado':<8} {'Discrep?':<9} {'Rector/a':<32} {'Inicio':<11} {'Fin':<11}")
    print("-" * 90)
    for r in records:
        print(f"{r['ces_cod']:<5} {str(r.get('siglas_ces') or ''):<8} {r.get('estado_extraccion', ''):<8} "
              f"{'SÍ' if r.get('discrepancia_nombre') else 'NO':<9} "
              f"{str(r.get('rector_nombre') or 'N/A')[:31]:<32} "
              f"{str(r.get('fecha_inicio_gestion') or 'N/A')[:10]:<11} "
              f"{str(r.get('fecha_fin_gestion') or 'N/A')[:10]:<11}")

if __name__ == "__main__":
    main()
