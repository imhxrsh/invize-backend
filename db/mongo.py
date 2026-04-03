from motor.motor_asyncio import AsyncIOMotorClient
from config.auth_settings import AuthSettings


settings = AuthSettings()
_client = AsyncIOMotorClient(settings.MONGO_URI)

# Default DB: for URIs ending with database name, get_default_database will use it
db = _client.get_default_database()


async def ensure_ttl_indexes():
    # TTL index on RefreshToken.expiresAt
    await db["RefreshToken"].create_index("expiresAt", expireAfterSeconds=0)
    # Optional: TTL for Session.lastUsed to auto-expire stale sessions (customize if desired)
    # await db["Session"].create_index("lastUsed", expireAfterSeconds=60 * 60 * 24 * 30)