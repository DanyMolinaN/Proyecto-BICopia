import requests
import urllib3
from collections import defaultdict
from datetime import datetime

urllib3.disable_warnings()
headers = {"User-Agent": "EPN-DWH-Scraper/2.0 (academic; contact: equipo6@epn.edu.ec)"}

targets = [
    ("ESPOCH (1002)", "https://www.espoch.edu.ec/wp-json/wp/v2/posts"),
    ("UCUENCA (1007)", "https://www.ucuenca.edu.ec/wp-json/wp/v2/posts"),
    ("IAEN (1057)", "https://www.iaen.edu.ec/wp-json/wp/v2/posts"),
    ("ESPE (1079)", "https://www.espe.edu.ec/wp-json/wp/v2/posts"),
]

for name, base_api in targets:
    url = f"{base_api}?per_page=50&page=1"
    try:
        r = requests.get(url, headers=headers, timeout=12, verify=False)
        total = r.headers.get("X-WP-Total", "desconocido")
        pages = r.headers.get("X-WP-TotalPages", "desconocido")
        print(f"\n=== {name} ===")
        print(f"Status: {r.status_code} | X-WP-Total: {total} | X-WP-TotalPages: {pages}")
        if r.status_code == 200:
            posts = r.json()
            if isinstance(posts, list) and posts:
                print(f"Posts obtenidos: {len(posts)}")
                fechas = [datetime.fromisoformat(p["date"]) for p in posts if p.get("date")]
                fechas.sort()
                print(f"Fecha min: {fechas[0].isoformat()} | Fecha max: {fechas[-1].isoformat()}")
                q_counts = defaultdict(int)
                for dt in fechas:
                    q = f"{dt.year}-T{(dt.month - 1) // 3 + 1}"
                    q_counts[q] += 1
                for q, c in sorted(q_counts.items()):
                    print(f"   {q}: {c} posts")
                print("Muestra:")
                for p in posts[:3]:
                    t = p.get("title", {}).get("rendered", "") if isinstance(p.get("title"), dict) else str(p.get("title"))
                    print(f"   - [{p.get('date')}] {t[:50]} -> {p.get('link')}")
    except Exception as e:
        print(f"Error {name}: {e}")
