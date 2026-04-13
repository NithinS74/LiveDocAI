# ─────────────────────────────────────────────────────────────
# 🤖 REALISTIC AUTO-TRAFFIC SIMULATOR (FIXED UUID BUG)
# ─────────────────────────────────────────────────────────────
from app.database import AsyncSessionLocal
from sqlalchemy import text
import jwt
from app.config import get_settings

async def simulate_demo_traffic():
    """Fires requests explicitly attached to your user token so they appear in your dashboard."""
    await asyncio.sleep(6) # Wait for server and DB to fully boot
    port = os.environ.get("PORT", "8000")
    
    # 127.0.0.1 is the safest loopback for Railway containers
    base_url = f"http://127.0.0.1:{port}" 
    
    logger.info(f"[Auto-Demo] Preparing to fire requests to {base_url}...")
    
    # 1. Grab the first registered user to attribute traffic to their dashboard
    headers = {}
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(text("SELECT id, email FROM users LIMIT 1"))
            user = result.fetchone()
            if user:
                # CRITICAL FIX: Cast user.id to string. Neon DB returns UUID objects which crash JWT encoder!
                settings = get_settings()
                token = jwt.encode({"sub": str(user.id), "email": user.email}, settings.secret_key, algorithm="HS256")
                headers["Authorization"] = f"Bearer {token}"
                logger.info(f"[Auto-Demo] Attaching traffic to user: {user.email}")
            else:
                logger.warning("[Auto-Demo] No users found! Please create an account in the UI first.")
                return # Abort if no user exists yet
    except Exception as e:
        logger.error(f"[Auto-Demo] Error fetching user for auth: {e}")
        return

    # 2. Fire the traffic with the Authorization header
    async with httpx.AsyncClient(base_url=base_url, headers=headers) as client:
        try:
            # GET Requests (Successful Reads)
            for _ in range(15):
                await client.get(f"/api/v1/products?category=software&limit=20")
                await asyncio.sleep(0.1)
                
            # POST Requests (Successful Creates)
            for i in range(5):
                await client.post(
                    "/api/v1/users", 
                    json={"name": f"Demo User {i}", "email": f"user{i}@acmecorp.com", "role": "customer"}
                )
                await asyncio.sleep(0.1)

            # PUT Requests (Successful Updates)
            for i in range(3):
                await client.put(
                    "/api/v1/users/usr_1001", 
                    json={"name": "Updated Name", "role": "admin"}
                )
                await asyncio.sleep(0.1)

            # DELETE Requests (Successful Deletes)
            await client.delete("/api/v1/users/usr_9999")
            await asyncio.sleep(0.1)

            # Error Requests (404 and 422 to populate the error charts)
            await client.get("/api/v1/products/prod_not_found") # 404 Not Found
            await client.post("/api/v1/users", json={"name": "Bad User"}) # 422 Validation Error
            
            logger.info("[Auto-Demo] Successfully generated all request types! Check Traffic Logs.")
        except Exception as e:
            logger.error(f"[Auto-Demo] Failed to simulate traffic: {e}")
