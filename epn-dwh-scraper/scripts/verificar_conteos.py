import sqlite3
import pandas as pd

conn = sqlite3.connect("epn-dwh-scraper/data/epn_dwh.db")
tables = ["stg_facultades", "stg_oferta", "stg_autoridades", "stg_institucional", "stg_publicaciones", "stg_oferta_sniese"]

print("=== CONTEO POR TABLA Y RUN_ID ===")
for t in tables:
    df = pd.read_sql(f"SELECT institucion_id, run_id, count(*) as count FROM {t} GROUP BY institucion_id, run_id", conn)
    print(f"\n[{t}] Total filas: {df['count'].sum() if len(df) > 0 else 0}")
    if len(df) == 0:
        print("  (0 registros)")
    else:
        for _, row in df.iterrows():
            print(f"  institucion: {row['institucion_id']} | run_id: {row['run_id']} | count: {row['count']}")

print("\n=== P3: PUBLICACIONES POR INSTITUCION, AÑO Y TRIMESTRE ===")
df_p3 = pd.read_sql("""
    SELECT 
        institucion_id,
        substr(fecha_publicacion, 1, 4) as anio,
        case 
            when substr(fecha_publicacion, 6, 2) in ('01','02','03') then 'T1'
            when substr(fecha_publicacion, 6, 2) in ('04','05','06') then 'T2'
            when substr(fecha_publicacion, 6, 2) in ('07','08','09') then 'T3'
            when substr(fecha_publicacion, 6, 2) in ('10','11','12') then 'T4'
            else 'Sin fecha'
        end as trimestre,
        count(*) as total
    FROM stg_publicaciones
    GROUP BY institucion_id, anio, trimestre
    ORDER BY institucion_id, anio, trimestre
""", conn)
print(df_p3.to_string(index=False))

print("\n=== PILOTOS: ROBOTS.TXT Y TERMINOS ===")
import urllib.request
for inst, url in [("ESPE", "https://www.espe.edu.ec/robots.txt"), ("USFQ", "https://www.usfq.edu.ec/robots.txt")]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"{inst} robots.txt: HTTP {resp.status}")
    except Exception as e:
        print(f"{inst} robots.txt error: {e}")
