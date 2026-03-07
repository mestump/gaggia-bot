import asyncio
import argparse
import sys

async def check_mode():
    import config
    import db
    import aiohttp
    await db.init_db()
    print(f"[OK] DB initialized at {config.DB_PATH}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://{config.GAGGIA_IP}/api/status",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                print(f"[OK] Device reachable: HTTP {resp.status}")
    except Exception as e:
        print(f"[WARN] Device not reachable: {e}")
    print("[OK] Config loaded — all checks complete")

async def main():
    import config
    import db
    await db.init_db()
    print("GaggiaMate bot starting... (stub)")
    await asyncio.sleep(999999)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        asyncio.run(check_mode())
    else:
        asyncio.run(main())
