"""Restart battery_tapo_control.py with a requested charging mode."""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psutil


VALID_MODES = ("schedule", "always_on", "auto")
DELAY_SECONDS = 300
TARGET_SCRIPT = Path(__file__).resolve().with_name("battery_tapo_control.py")
TARGET_SCRIPT_NAME = TARGET_SCRIPT.name.lower()
HELPER_SCRIPT_NAME = Path(__file__).name.lower()
PENDING_STATE_FILE = Path(__file__).resolve().with_name(
    "battery_tapo_mode_switch.pending.json"
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Restart battery_tapo_control.py with a new charging mode"
    )
    parser.add_argument(
        "--mode",
        choices=VALID_MODES,
        required=True,
        help="Mode to launch after restart",
    )
    return parser.parse_args()


def load_pending_state():
    try:
        return json.loads(PENDING_STATE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None


def save_pending_state(state):
    temp_file = PENDING_STATE_FILE.with_name(PENDING_STATE_FILE.name + ".tmp")
    temp_file.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    temp_file.replace(PENDING_STATE_FILE)


def clear_pending_state(expected_request_id=None):
    if expected_request_id is not None:
        state = load_pending_state()
        if not state or state.get("request_id") != expected_request_id:
            return

    try:
        PENDING_STATE_FILE.unlink()
    except FileNotFoundError:
        pass


def is_helper_process(process):
    try:
        cmdline = process.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False

    return any(Path(arg).name.lower() == HELPER_SCRIPT_NAME for arg in cmdline)


def cancel_pending_switch():
    state = load_pending_state()
    if not state:
        return

    pending_pid = state.get("helper_pid")
    if pending_pid and pending_pid != os.getpid():
        try:
            pending_process = psutil.Process(pending_pid)
            if is_helper_process(pending_process):
                pending_process.terminate()
                try:
                    pending_process.wait(timeout=5)
                except psutil.TimeoutExpired:
                    pending_process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    clear_pending_state()


def extract_mode(cmdline):
    for index, arg in enumerate(cmdline):
        if arg == "--mode" and index + 1 < len(cmdline):
            mode = cmdline[index + 1].strip().lower()
            if mode in VALID_MODES:
                return mode
        if arg.startswith("--mode="):
            mode = arg.split("=", 1)[1].strip().lower()
            if mode in VALID_MODES:
                return mode
    return "schedule"


def matches_target_script(cmdline):
    return any(Path(arg).name.lower() == TARGET_SCRIPT_NAME for arg in cmdline)


def find_running_instances():
    instances = []
    current_pid = os.getpid()

    for proc in psutil.process_iter(["pid", "cmdline"]):
        if proc.info.get("pid") == current_pid:
            continue

        try:
            cmdline = proc.info.get("cmdline") or []
            if matches_target_script(cmdline):
                instances.append((proc, extract_mode(cmdline)))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return instances


def stop_processes(instances):
    processes = [proc for proc, _ in instances]

    for process in processes:
        try:
            process.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    _, alive = psutil.wait_procs(processes, timeout=5)

    for process in alive:
        try:
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if alive:
        psutil.wait_procs(alive, timeout=5)


def launch_target(mode):
    return subprocess.Popen(
        [sys.executable, str(TARGET_SCRIPT), "--mode", mode],
        cwd=str(TARGET_SCRIPT.parent),
    )


def main():
    args = parse_args()
    cancel_pending_switch()
    instances = find_running_instances()
    current_modes = {mode for _, mode in instances}
    request_id = uuid.uuid4().hex
    delayed_switch = False

    if instances and current_modes == {args.mode}:
        print(f"Already running in {args.mode} mode.")
        return 0

    try:
        if args.mode != "always_on" and "always_on" in current_modes and instances:
            delayed_switch = True
            save_pending_state(
                {
                    "request_id": request_id,
                    "helper_pid": os.getpid(),
                    "target_mode": args.mode,
                    "delay_seconds": DELAY_SECONDS,
                }
            )
            print(
                f"Found always_on instance. Switching to {args.mode} in {DELAY_SECONDS} seconds..."
            )
            for _ in range(DELAY_SECONDS):
                state = load_pending_state()
                if not state or state.get("request_id") != request_id:
                    print("Pending switch canceled.")
                    return 0
                time.sleep(1)

            state = load_pending_state()
            if not state or state.get("request_id") != request_id:
                print("Pending switch canceled.")
                return 0

            instances = find_running_instances()

        if instances:
            print(f"Stopping {len(instances)} running instance(s)...")
            stop_processes(instances)
        else:
            print("No running instance found.")

        process = launch_target(args.mode)
        print(f"Started {TARGET_SCRIPT.name} with mode={args.mode} (pid {process.pid})")
    finally:
        if delayed_switch:
            clear_pending_state(request_id)


if __name__ == "__main__":
    raise SystemExit(main())