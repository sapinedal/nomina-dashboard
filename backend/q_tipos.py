import sqlite3, pandas as pd
conn = sqlite3.connect('nomina_dashboard.db')
df = pd.read_sql("""
    SELECT tipo_novedad, unidad, COUNT(*) as cnt,
           ROUND(AVG(CAST(dias AS REAL)),1) as avg_dias,
           ROUND(SUM(CAST(dias AS REAL)),0) as total_dias
    FROM novedades_nomina WHERE es_valido=1
    GROUP BY tipo_novedad, unidad ORDER BY cnt DESC
""", conn)
pd.set_option('display.max_rows', 100)
pd.set_option('display.width', 120)
print(df.to_string())
conn.close()
