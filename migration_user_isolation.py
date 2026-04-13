"""
Migration: Add user_id columns — run ONCE before starting the server.
Safe to run multiple times (uses IF NOT EXISTS).

Usage:
    python migration_user_isolation.py
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import AsyncSessionLocal
from sqlalchemy import text

async def run():
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(text("ALTER TABLE api_logs ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)"))
            await db.execute(text("ALTER TABLE endpoints ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)"))
            await db.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS api_key VARCHAR(100)"))
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_api_logs_user_id ON api_logs(user_id)"))
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_endpoints_user_id ON endpoints(user_id)"))
            await db.commit()
            print("✅ Migration complete!")
        except Exception as e:
            await db.rollback()
            print(f"❌ Migration failed: {e}")
            raise

asyncio.run(run())
