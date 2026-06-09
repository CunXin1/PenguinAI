#!/usr/bin/env python3
"""PenguinAI service status checker — `make status` or `python scripts/status.py`."""

import json
import socket
import sys
import time
from urllib.request import Request, urlopen

RESET = "\033[0m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
DIM = "\033[2m"


def _icon(ok: bool | None) -> str:
    if ok is True:
        return f"{GREEN}UP{RESET}"
    if ok is False:
        return f"{RED}DOWN{RESET}"
    return f"{YELLOW}???{RESET}"


def check_port(host: str, port: int, timeout: float = 2.0) -> tuple[bool, float]:
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, (time.perf_counter() - t0) * 1000
    except (OSError, TimeoutError):
        return False, 0


def check_http(url: str, timeout: float = 3.0) -> tuple[bool, int | None, float, dict | None]:
    t0 = time.perf_counter()
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=timeout) as resp:
            latency = (time.perf_counter() - t0) * 1000
            body = resp.read().decode()
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = None
            return True, resp.status, latency, data
    except Exception:
        return False, None, 0, None


def check_redis(host: str = "127.0.0.1", port: int = 6379) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=2) as sock:
            sock.sendall(b"PING\r\n")
            resp = sock.recv(64).decode().strip()
            return resp == "+PONG", resp
    except Exception as e:
        return False, str(e)


def main():
    print(f"\n{BOLD}=== PenguinAI Service Status ==={RESET}\n")

    results = []

    # 1. TimescaleDB
    ok, latency = check_port("127.0.0.1", 5432)
    results.append(("TimescaleDB", ok, f"{latency:.0f}ms" if ok else "unreachable", "127.0.0.1:5432"))

    # 2. Redis
    ok, detail = check_redis()
    results.append(("Redis", ok, detail if ok else detail[:60], "127.0.0.1:6379"))

    # 3. Backend API
    ok, status, latency, data = check_http("http://127.0.0.1:8000/health")
    if ok and data:
        overall = data.get("status", "?")
        sv = data.get("realtime", {}).get("supervisor", "?")
        detail = f"HTTP {status} | status={overall} | realtime={sv} | {latency:.0f}ms"
    elif ok:
        detail = f"HTTP {status} | {latency:.0f}ms"
    else:
        detail = "unreachable"
    results.append(("Backend API", ok, detail, "127.0.0.1:8000"))

    # 4. Frontend
    ok, status, latency, _ = check_http("http://127.0.0.1:3000")
    detail = f"HTTP {status} | {latency:.0f}ms" if ok else "unreachable"
    results.append(("Frontend", ok, detail, "127.0.0.1:3000"))

    # 5. Celery (worker + beat from /health response)
    if data and isinstance(data, dict):
        celery_info = data.get("celery", {})
        for role in ("worker", "beat"):
            info = celery_info.get(role, {})
            st = info.get("status", "unknown")
            pid = info.get("pid")
            restarts = info.get("restarts", 0)
            role_ok = st == "running"
            detail = f"{st} | pid={pid} | restarts={restarts}" if st != "disabled" else "disabled"
            results.append((f"Celery {role.title()}", role_ok if st != "disabled" else None,
                            detail, "subprocess"))
    else:
        results.append(("Celery Worker", None, "backend unreachable", "subprocess"))
        results.append(("Celery Beat", None, "backend unreachable", "subprocess"))

    # 6. Realtime supervisor (from /health response)
    if data and isinstance(data, dict):
        rt = data.get("realtime", {})
        sv_status = rt.get("supervisor", "unknown")
        pid = rt.get("pid")
        restarts = rt.get("restarts", 0)
        sv_ok = sv_status == "running"
        sv_detail = f"{sv_status} | pid={pid} | restarts={restarts}"
        results.append(("Realtime Supervisor", sv_ok if sv_status != "disabled" else None,
                        sv_detail, "subprocess"))

        services = rt.get("services", {})
        for svc in ("ibkr", "finnhub"):
            info = services.get(svc, {})
            alive = info.get("alive", False)
            uptime = info.get("uptime_s", 0)
            results.append((f"  {svc.upper()} Stream", alive,
                            f"uptime={uptime:.0f}s" if alive else "down", "WS"))
    else:
        results.append(("Realtime Supervisor", None, "backend unreachable", "subprocess"))

    # 7. Flower (optional)
    ok, _, latency, _ = check_http("http://127.0.0.1:5555")
    if ok:
        results.append(("Flower Monitor", True, f"{latency:.0f}ms", "127.0.0.1:5555"))
    else:
        results.append(("Flower Monitor", False, "not running (optional)", "127.0.0.1:5555"))

    # Print table
    name_w = max(len(r[0]) for r in results) + 2
    for name, ok, detail, addr in results:
        status_str = _icon(ok)
        print(f"  {name:<{name_w}} {status_str:<16} {DIM}{detail}{RESET}  {DIM}({addr}){RESET}")

    print()

    # Summary
    up = sum(1 for _, ok, _, _ in results if ok is True)
    down = sum(1 for _, ok, _, _ in results if ok is False)
    unknown = sum(1 for _, ok, _, _ in results if ok is None)
    print(f"  {GREEN}{up} up{RESET}  {RED}{down} down{RESET}  {YELLOW}{unknown} unknown{RESET}")
    print()

    critical = {"TimescaleDB", "Redis", "Backend API", "Frontend", "Celery Worker", "Celery Beat"}
    critical_down = any(ok is False and name in critical for name, ok, _, _ in results)
    return 1 if critical_down else 0


if __name__ == "__main__":
    sys.exit(main())
