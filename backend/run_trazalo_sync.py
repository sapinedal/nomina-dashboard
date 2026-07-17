# -*- coding: utf-8 -*-
import sys; sys.path.insert(0, '.')
from app.database import SessionLocal
from app.services.trazalo_sync import sync_trazalo

db = SessionLocal()
try:
    result = sync_trazalo(db)
    print("RESULTADO:", result)
finally:
    db.close()
