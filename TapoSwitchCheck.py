import asyncio
import sys
import time

shutdown_event = asyncio.Event()

async def timer():
    try:
        while True:
            print(f"[{time.strftime('%H:%M:%S')}] tick")
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass
    finally:
        print("cleanup done")

async def main():
    print("started")
    await timer()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        shutdown_event.set()
        print("ctrl+c received")
