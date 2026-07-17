import sys; sys.path.insert(0, '.')
from app.database import SessionLocal
from app.services.excel_processor import run_etl_process

db = SessionLocal()
print("Iniciando ETL completo (todos los archivos)...")
result = run_etl_process(db, triggered_by="admin-fix")
print(f"\nResultado:")
print(f"  Estado        : {result.get('status')}")
print(f"  Archivos OK   : {result.get('files_processed')}")
print(f"  Archivos error: {result.get('files_failed')}")
print(f"  Registros     : {result.get('records_inserted')}")
print(f"  Inválidos     : {result.get('records_invalid')}")
db.close()
