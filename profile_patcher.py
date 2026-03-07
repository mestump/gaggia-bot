import json
import logging
import aiohttp
import db
import config

logger = logging.getLogger(__name__)

_PROFILE_URL = f"http://{config.GAGGIA_IP}/api/profile"


async def patch_profile(adjustments: list) -> dict:
    """Apply adjustments to device profile with snapshot and verification.

    Fetches the current profile via GET /api/profile, snapshots it to the DB,
    applies the given adjustments, PUTs the patched profile back, then verifies
    with a final GET.

    Args:
        adjustments: list of dicts with keys step_name, field, new_value.

    Returns:
        dict with keys success (bool) and profile (the verified profile dict).
    """
    async with aiohttp.ClientSession() as session:
        # Snapshot current profile
        async with session.get(_PROFILE_URL) as resp:
            resp.raise_for_status()
            current = await resp.json()

        async with db.get_db() as conn:
            await conn.execute(
                "INSERT INTO profiles (name, raw_json, source) VALUES (?,?,?)",
                (current.get("name"), json.dumps(current), "device"),
            )
            await conn.commit()

        # Apply adjustments (deep copy via JSON round-trip)
        patched = json.loads(json.dumps(current))
        steps = {s["name"]: s for s in patched.get("steps", [])}
        for adj in adjustments:
            step = steps.get(adj["step_name"])
            if step and adj["field"] in step:
                step[adj["field"]] = adj["new_value"]

        # PUT and verify
        async with session.put(_PROFILE_URL, json=patched) as resp:
            resp.raise_for_status()

        async with session.get(_PROFILE_URL) as resp:
            resp.raise_for_status()
            verified = await resp.json()

        if verified.get("name") != current.get("name"):
            logger.warning(
                "Profile name mismatch after patch: expected %s, got %s",
                current.get("name"),
                verified.get("name"),
            )

        logger.info("Profile patched and verified: %s", verified.get("name"))
        return {"success": True, "profile": verified}
