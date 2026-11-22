"""
Script para ejecutar P3 (Noticias / WP API) en dos instituciones adicionales con WordPress.

IES seleccionadas:
- 1002: Escuela Superior Politécnica de Chimborazo (ESPOCH) - https://www.espoch.edu.ec/wp-json/wp/v2/posts
- 1022: Universidad Andina Simón Bolívar (UASB) - https://www.uasb.edu.ec/wp-json/wp/v2/posts
(Alternativa: 1007 UCUENCA)
"""

import json
from datetime import datetime
from collections import defaultdict
from src.utils.http_client import HttpClient

def analizar_ies_wp(nombre, api_url, max_pages=3):
    print(f"\n=======================================================")
    print(f"Probando P3 WordPress API: {nombre}")
    print(f"Endpoint: {api_url}")
    print(f"=======================================================")
    client = HttpClient(use_cache=True, institucion_id=nombre[:4])
    
    posts = []
    headers = {}
    for page in range(1, max_pages + 1):
        url = f"{api_url}?per_page=50&page={page}"
        print(f"Consultando página {page}: {url}...")
        resp = client.get_response(url) if hasattr(client, "get_response") else None
        
        # Fallback usando requests con session del client
        r = client.session.get(url, timeout=15, verify=False)
        print(f"  HTTP Status: {r.status_code}")
        if r.status_code != 200:
            print(f"  Fin de paginación o error en pág {page}: status {r.status_code}")
            break
        
        total_posts = r.headers.get("X-WP-Total", "desconocido")
        total_pages = r.headers.get("X-WP-TotalPages", "desconocido")
        print(f"  Cabeceras: X-WP-Total = {total_posts}, X-WP-TotalPages = {total_pages}")
        
        data = r.json()
        if not data or not isinstance(data, list):
            break
        posts.extend(data)
        if str(page) == str(total_pages):
            break

    print(f"Total posts obtenidos: {len(posts)}")
    if not posts:
        print("No se recuperaron posts.")
        return

    # Análisis de fechas
    fechas = []
    conteo_trimestres = defaultdict(int)
    for p in posts:
        date_str = p.get("date") or p.get("date_gmt")
        if date_str:
            try:
                dt = datetime.fromisoformat(date_str)
                fechas.append(dt)
                trimestre = f"{dt.year}-T{(dt.month - 1) // 3 + 1}"
                conteo_trimestres[trimestre] += 1
            except Exception:
                pass

    if fechas:
        fechas.sort()
        print(f"Fecha más antigua: {fechas[0].isoformat()}")
        print(f"Fecha más reciente: {fechas[-1].isoformat()}")
        print("\nDistribución por Año y Trimestre:")
        for q in sorted(conteo_trimestres.keys()):
            print(f"  {q}: {conteo_trimestres[q]} noticias")
            
        print("\nMuestra de 5 noticias:")
        for p in posts[:5]:
            title = p.get("title", {}).get("rendered", "") if isinstance(p.get("title"), dict) else str(p.get("title"))
            print(f"  - [{p.get('date')}] {title[:60]}... -> {p.get('link')}")

if __name__ == "__main__":
    analizar_ies_wp("ESPOCH (1002)", "https://www.espoch.edu.ec/wp-json/wp/v2/posts", max_pages=3)
    analizar_ies_wp("UASB (1022)", "https://www.uasb.edu.ec/wp-json/wp/v2/posts", max_pages=3)
