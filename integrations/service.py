"""Read/write integration config (e.g. ERP type) from DB. Fallback to env."""
import os
from typing import Optional

from prisma import Prisma

INTEGRATION_KEY_ERP_TYPE = "erp_type"
VALID_ERP_TYPES = ("demo", "rest", "stub")


async def get_erp_type(prisma: Prisma) -> str:
    """Get current ERP type from DB or env."""
    try:
        row = await prisma.integrationconfig.find_unique(where={"key": INTEGRATION_KEY_ERP_TYPE})
        if row and row.value in VALID_ERP_TYPES:
            return row.value
    except Exception:
        pass
    env_type = (os.getenv("ERP_TYPE", "demo") or "demo").lower().strip()
    return env_type if env_type in VALID_ERP_TYPES else "demo"


async def set_erp_type(prisma: Prisma, value: str) -> str:
    """Set ERP type in DB. Value must be one of VALID_ERP_TYPES."""
    if value not in VALID_ERP_TYPES:
        raise ValueError(f"Invalid erp_type. Must be one of: {VALID_ERP_TYPES}")
    try:
        await prisma.integrationconfig.upsert(
            where={"key": INTEGRATION_KEY_ERP_TYPE},
            data={
                "create": {"key": INTEGRATION_KEY_ERP_TYPE, "value": value},
                "update": {"value": value},
            },
        )
        return value
    except Exception as e:
        raise ValueError(f"Failed to save: {e}") from e
