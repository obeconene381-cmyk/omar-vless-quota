import os
import sys
import time
import json
import requests
import subprocess
import re

VPS_URL = os.getenv("VPS_URL", "http://35.171.3.190:5000")
XRAY_API_SERVER = "127.0.0.1:10085"

# تعيين المتغير البيئي حتى لا نحتاج تمريره في كل أمر
os.environ["XRAY_API_SERVER"] = XRAY_API_SERVER

if not os.path.exists("./xray"):
    print("[-] Critical: ./xray binary not found!", flush=True)
    sys.exit(1)

print("[*] Launching Xray Core inside container...", flush=True)
try:
    subprocess.Popen(["./xray", "-config", "config.json"])
    print("[+] Xray Core launched successfully in background.", flush=True)
except Exception as e:
    print(f"[-] Critical: Failed to start Xray Core: {e}", flush=True)
    sys.exit(1)

time.sleep(5)

print(f"[+] Monitor Daemon Started. Target VPS: {VPS_URL}", flush=True)

def get_user_traffic(email):
    try:
        cmd = [
            "./xray", "api", "statsquery",
            "-pattern", f"user>>{email}"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)

        if res.returncode != 0 or not res.stdout:
            return 0

        # محاولة قراءة JSON أولاً
        try:
            data = json.loads(res.stdout)
            total = 0
            if "stat" in data:
                if isinstance(data["stat"], list):
                    for item in data["stat"]:
                        total += int(item.get("value", 0))
                elif isinstance(data["stat"], dict):
                    total = int(data["stat"].get("value", 0))
            if total > 0:
                return total
        except:
            pass

        # الاحتياط باستخدام Regex
        values = re.findall(r'"value":\s*"(\d+)"', res.stdout)
        if not values:
            values = re.findall(r'value:\s*(\d+)', res.stdout)
        if values:
            return sum(int(v) for v in values)

    except Exception as e:
        print(f"[-] Error parsing traffic for {email}: {e}", flush=True)
    return 0

def report_usage(email, bytes_used):
    try:
        url = f"{VPS_URL}/report_usage"
        payload = {"email": email, "bytes": bytes_used}
        res = requests.post(url, json=payload, timeout=5)
        if res.status_code == 200:
            print(f"[+] Reported {bytes_used} bytes for {email}", flush=True)
            return True
    except Exception as e:
        print(f"[-] Failed to report: {e}", flush=True)
    return False

def fetch_active_users():
    try:
        res = requests.get(f"{VPS_URL}/get_active_users", timeout=5)
        if res.status_code == 200:
            return res.json()
        print(f"[-] Failed fetching users. Code: {res.status_code}", flush=True)
        return None
    except Exception as e:
        print(f"[-] Network error: {e}", flush=True)
        return None

reported_bytes = {}
current_xray_users = set()

while True:
    print("[*] Starting Sync Cycle...", flush=True)
    active_users = fetch_active_users()

    if active_users is not None:
        active_emails = {u["email"] for u in active_users}

        # إضافة المستخدمين
        for user in active_users:
            email = user["email"]
            uuid = user["uuid"]
            if email not in current_xray_users:
                payload = f'tag: "vless-in" operation: {{ add_user: {{ user: {{ email: "{email}" id: "{uuid}" }} }} }}'
                cmd = [
                    "./xray", "api",
                    "xray.app.proxyman.command.HandlerService.AlterInbound",
                    payload
                ]
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    current_xray_users.add(email)
                    print(f"[+] Injected {email}", flush=True)
                else:
                    print(f"[-] Rejected {email}: {res.stderr.strip()}", flush=True)

        # حساب الاستهلاك
        for email in list(current_xray_users):
            xray_total = get_user_traffic(email)

            if xray_total > 0:
                if email not in reported_bytes:
                    reported_bytes[email] = 0
                if xray_total < reported_bytes[email]:
                    reported_bytes[email] = 0
                delta = xray_total - reported_bytes[email]
                if delta > 0:
                    if report_usage(email, delta):
                        reported_bytes[email] = xray_total

            # حذف المستخدمين غير النشطين
            if email not in active_emails:
                payload = f'tag: "vless-in" operation: {{ remove_user: {{ email: "{email}" }} }}'
                cmd = [
                    "./xray", "api",
                    "xray.app.proxyman.command.HandlerService.AlterInbound",
                    payload
                ]
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    current_xray_users.remove(email)
                    if email in reported_bytes:
                        del reported_bytes[email]
                    print(f"[-] Removed {email}", flush=True)
                else:
                    print(f"[-] Failed to remove {email}: {res.stderr.strip()}", flush=True)
    else:
        print("[!] Sync skipped", flush=True)

    time.sleep(15)
