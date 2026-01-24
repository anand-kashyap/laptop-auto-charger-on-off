import sys
import asyncio
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import psutil
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, time
from dotenv import load_dotenv
import os
from plugp100.common.credentials import AuthCredential
from plugp100.new.device_factory import connect, DeviceConnectConfiguration
from plugp100.new.components.on_off_component import OnOffComponent
from aiohttp import ClientSession

load_dotenv()

# ---------------- CONFIG ----------------
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))
LOW_THRESHOLD = int(os.getenv("LOW_THRESHOLD", "35"))
HIGH_THRESHOLD = int(os.getenv("HIGH_THRESHOLD", "85"))
CRITICAL_THRESHOLD = int(os.getenv("CRITICAL_THRESHOLD", "25"))

FORCE_NOTIFY_TEST = os.getenv("FORCE_NOTIFY_TEST", "False").lower() == "true"

TAPO_IP = os.getenv("TAPO_IP", "")
TAPO_EMAIL = os.getenv("TAPO_EMAIL", "")
TAPO_PASSWORD = os.getenv("TAPO_PASSWORD", "")

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "https://ntfy.sh/<topic>")

LOG_FILE = os.getenv("LOG_FILE", "battery_tapo_log.txt")
MAX_LOG_SIZE = int(os.getenv("MAX_LOG_SIZE", str(5 * 1024 * 1024)))
BACKUP_COUNT = int(os.getenv("BACKUP_COUNT", "3"))

START_TIME_STR = os.getenv("START_TIME", "22:00")
END_TIME_STR = os.getenv("END_TIME", "12:00")
START_TIME = datetime.strptime(START_TIME_STR, "%H:%M").time()
END_TIME = datetime.strptime(END_TIME_STR, "%H:%M").time()
# ----------------------------------------


shutdown_event = asyncio.Event()

logger = logging.getLogger("BatteryTapoMonitor")
logger.setLevel(logging.INFO)

handler = RotatingFileHandler(LOG_FILE, maxBytes=MAX_LOG_SIZE, backupCount=BACKUP_COUNT)
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

console = logging.StreamHandler()
console.setFormatter(formatter)
logger.addHandler(console)

def log(msg, level="info"):
    getattr(logger, level)(msg)

def get_battery_percent():
    battery = psutil.sensors_battery()
    return battery.percent if battery else None

def is_night_window():
    FORCE_NIGHT_MODE = False
    if FORCE_NIGHT_MODE:
        return True
    now = datetime.now().time()
    return now >= START_TIME or now <= END_TIME

async def send_ntfy(message, priority=3):
    try:
        async with ClientSession() as session:
            await session.post(
                NTFY_TOPIC,
                data=message.encode("utf-8"),
                headers={
                    "Content-Type": "text/plain",
                    "Priority": str(priority),
                }
            )
    except Exception as e:
        log(f"ntfy notification failed: {e}", "warning")

async def connect_plug():
    credentials = AuthCredential(TAPO_EMAIL, TAPO_PASSWORD)
    config = DeviceConnectConfiguration(host=TAPO_IP, credentials=credentials)
    device = await connect(config)
    await device.update()

    onoff = next(
        (c for c in device.get_device_components if isinstance(c, OnOffComponent)),
        None
    )
    return device, onoff

async def monitor_battery():
    device, onoff = None, None
    first_state_read = True
    tapo_was_down = False

    try:
        while True:
            percent = get_battery_percent()
            if percent is None:
                log("Unable to read battery info.", "warning")
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            if not device or not onoff:
                log("Connecting to Tapo plug...")
                try:
                    device, onoff = await connect_plug()
                    log("Connected to Tapo plug")

                    if tapo_was_down:
                        await send_ntfy(
                            "✅ Power restored / Tapo plug reachable again.",
                            priority=3
                        )
                        tapo_was_down = False

                    first_state_read = True

                except Exception as e:
                    log(f"Tapo connect failed: {e}", "warning")

                    if not tapo_was_down and (FORCE_NOTIFY_TEST or percent < CRITICAL_THRESHOLD):
                        await send_ntfy(
                            f"⚠️ Battery {percent}% and Tapo plug unreachable. Possible power outage or switch off.",
                            priority=5
                        )
                        tapo_was_down = True

                    device, onoff = None, None
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue

            if not first_state_read:
                try:
                    await device.update()
                except Exception as e:
                    log(f"Tapo Plug unreachable(poweroff maybe): {e}", "warning")

                    if not tapo_was_down and (FORCE_NOTIFY_TEST or percent < CRITICAL_THRESHOLD):
                        await send_ntfy(
                            f"⚠️ Battery {percent}% and Tapo plug unreachable. Possible power outage or switch off.",
                            priority=5
                        )
                        tapo_was_down = True

                    device, onoff = None, None
                    continue
            else:
                first_state_read = False

            plug_on = onoff.device_on
            mode = "ALWAYS_CHARGING" if not is_night_window() else "AUTO_CHARGE"
            log(f"Battery: {percent}% | Plug is {'ON' if plug_on else 'OFF'} | Mode: {mode}")

            if not is_night_window():
                if not plug_on:
                    await onoff.turn_on()
            else:
                if percent > HIGH_THRESHOLD and plug_on:
                    await onoff.turn_off()
                elif percent < LOW_THRESHOLD and not plug_on:
                    await onoff.turn_on()

            await asyncio.sleep(CHECK_INTERVAL)

    except asyncio.CancelledError:
        log("Shutdown requested")
        raise

async def main():
    log("Battery monitor started...")
    await monitor_battery()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
