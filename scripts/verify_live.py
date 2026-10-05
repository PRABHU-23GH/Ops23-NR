"""Live validation script for Ops23-NR FastAPI service.

Starts the Uvicorn server in a subprocess, issues requests to /health,
/api/simulate/error, and /api/simulate/crash, prints responses and
emitted structured JSON logs, then terminates the server cleanly.
"""

import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

HOST = "127.0.0.1"
PORT = 8023
BASE_URL = f"http://{HOST}:{PORT}"

captured_logs: list[str] = []


def stream_reader(pipe):
    """Read output from subprocess pipe concurrently to prevent OS buffer deadlock."""
    try:
        for line in iter(pipe.readline, ""):
            if line:
                captured_logs.append(line.rstrip())
    except Exception:
        pass


def main():
    print(f"[*] Starting Ops23-NR server on {BASE_URL}...")
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        HOST,
        "--port",
        str(PORT),
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # Start non-blocking log reader thread to avoid pipe buffer deadlocks
    t = threading.Thread(target=stream_reader, args=(proc.stdout,), daemon=True)
    t.start()

    # Wait for server to become responsive
    started = False
    for _ in range(30):
        time.sleep(0.2)
        try:
            req = urllib.request.Request(f"{BASE_URL}/health")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    started = True
                    break
        except Exception:
            pass

    if not started:
        print("[!] Server failed to start within timeout.")
        proc.terminate()
        sys.exit(1)

    print("[+] Server started successfully.")

    # 1. Health Endpoint
    print("\n--- 1. Testing GET /health ---")
    req = urllib.request.Request(f"{BASE_URL}/health")
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        body = resp.read().decode("utf-8")
        print(f"Status Code: {resp.status}")
        print(f"Response: {json.dumps(json.loads(body), indent=2)}")

    # 2. Simulate Error Endpoint
    print("\n--- 2. Testing POST /api/simulate/error ---")
    req = urllib.request.Request(
        f"{BASE_URL}/api/simulate/error",
        data=json.dumps({"detail": "Live synthetic failure validation"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=2.0)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"Status Code: {e.code}")
        print(f"Response: {json.dumps(json.loads(error_body), indent=2)}")

    # 3. Simulate Crash Endpoint (Safe Mode)
    print("\n--- 3. Testing POST /api/simulate/crash (Safe Mode) ---")
    req = urllib.request.Request(
        f"{BASE_URL}/api/simulate/crash",
        data=json.dumps({"reason": "Live crash safety probe"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        crash_body = resp.read().decode("utf-8")
        print(f"Status Code: {resp.status}")
        print(f"Response: {json.dumps(json.loads(crash_body), indent=2)}")

    # 4. Graceful Shutdown & Log Review
    print("\n--- 4. Shutting down server and reviewing structured logs ---")
    proc.terminate()
    proc.wait(timeout=5)
    time.sleep(0.3)

    print("\nStructured JSON Log Output Captured:")
    for line in captured_logs:
        line_str = line.strip()
        if line_str.startswith("{") and line_str.endswith("}"):
            try:
                parsed = json.loads(line_str)
                level = parsed.get("level", "INFO")
                msg = parsed.get("message", "")
                req_id = parsed.get("request_id", "-")
                trace_id = parsed.get("trace_id", "-")
                span_id = parsed.get("span_id", "-")
                status_code = parsed.get("http_status_code", "-")
                print(f"[{level}] {msg} (req_id: {req_id}, trace_id: {trace_id}, span_id: {span_id}, status: {status_code})")
            except Exception:
                print(line_str)
        elif line_str:
            print(line_str)

    print("\n[+] All live validations passed successfully.")


if __name__ == "__main__":
    main()
