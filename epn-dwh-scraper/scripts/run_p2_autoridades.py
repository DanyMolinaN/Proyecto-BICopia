"""
Script para generar el reporte de autoridades (P2) para EPN y ESPE.

Campos requeridos:
- nombre
- cargo_original
- cargo_normalizado
- facultad
- condicion_designacion
- evidencia_condicion
- fuente_url

Además:
- Conteo de decanos vs facultades oficiales
- Distribución de condicion_designacion basada en evidencia textual
"""

import csv
from src.instituciones import load_ces64, InstitucionConfig
from src.scrapers.autoridades_scraper import AutoridadesScraper
from src.utils.http_client import HttpClient

def extraer_autoridades(inst_id, nombre, url_autoridades=None):
    print(f"\n=======================================================")
    print(f"Extrayendo Autoridades P2: {nombre} ({inst_id})")
    print(f"=======================================================")
    
    reg = load_ces64()
    inst = reg.get(inst_id)
    if not inst:
        inst = InstitucionConfig({
            "id": inst_id, "nombre": nombre, "sigla": inst_id,
            "base_url": url_autoridades or "https://www.espe.edu.ec",
            "portal_url": url_autoridades or "https://www.espe.edu.ec",
            "endpoints": {"autoridades": url_autoridades or f"https://www.{inst_id.lower()}.edu.ec/autoridades"}
        })
    elif url_autoridades:
        endpoints = dict(inst.endpoints)
        endpoints["autoridades"] = url_autoridades
        data = {
            "id": inst.id,
            "nombre": inst.nombre,
            "sigla": inst.sigla,
            "base_url": inst.base_url,
            "portal_url": inst.portal_url,
            "endpoints": endpoints,
            "adaptador": inst.adaptador,
            "estado_integracion": inst.estado_integracion,
            "tipo_institucional": inst.tipo_institucional,
            "financiamiento": inst.financiamiento,
        }
        inst = InstitucionConfig(data)

    client = HttpClient(use_cache=True, institucion_id=inst_id)
    scraper = AutoridadesScraper(http_client=client, institucion_id=inst_id, institucion=inst)
    records = scraper.extract()
    print(f"Total autoridades extraídas: {len(records)}")

    # Análisis
    decanos = [r for r in records if "DECAN" in (r.get("cargo_normalizado") or "").upper() or "DECAN" in (r.get("cargo_original") or "").upper()]
    subdecanos = [r for r in records if "SUBDECAN" in (r.get("cargo_normalizado") or "").upper() or "SUBDECAN" in (r.get("cargo_original") or "").upper()]
    rectores = [r for r in records if "RECTOR" in (r.get("cargo_normalizado") or "").upper()]
    vicerrectores = [r for r in records if "VICERRECTOR" in (r.get("cargo_normalizado") or "").upper()]
    
    print(f"  Rectores/as     : {len(rectores)}")
    print(f"  Vicerrectores/as: {len(vicerrectores)}")
    print(f"  Decanos/as      : {len(decanos)}")
    print(f"  Subdecanos/as   : {len(subdecanos)}")

    # Distribución condicion_designacion
    condiciones = {}
    for r in records:
        c = r.get("condicion_designacion") or "no_especificado"
        condiciones[c] = condiciones.get(c, 0) + 1
    print("  Distribución condición designación:")
    for c, cnt in condiciones.items():
        print(f"    - {c}: {cnt}")

    print("\nTabla detallada:")
    print(f"{'Nombre':<30} {'Cargo Original':<25} {'Cargo Norm':<16} {'Facultad':<30} {'Condición':<12} {'Evidencia':<20}")
    print("-" * 140)
    for r in records:
        print(f"{str(r.get('nombre_completo') or r.get('nombre') or ''):<30} "
              f"{str(r.get('cargo_original') or r.get('cargo') or '')[:24]:<25} "
              f"{str(r.get('cargo_normalizado') or '')[:15]:<16} "
              f"{str(r.get('facultad') or r.get('unidad_academica') or 'N/A')[:29]:<30} "
              f"{str(r.get('condicion_designacion') or 'N/A'):<12} "
              f"{str(r.get('evidencia_condicion') or 'N/A')[:19]:<20}")
              
    return records

if __name__ == "__main__":
    epn_records = extraer_autoridades("1001", "Escuela Politécnica Nacional", "https://www.epn.edu.ec/autoridades")
    espe_records = extraer_autoridades("1079", "Universidad de las Fuerzas Armadas ESPE", "https://www.espe.edu.ec/autoridades")
