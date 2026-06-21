import os
import sys
import time
import json
import requests
import subprocess
import re

VPS_URL = os.getenv("VPS_URL", "http://35.171.3.190:5000")
XRAY_API_SERVER = "127.0.0.1:10085"

# 🛠️ التحسين تع كلاود: التأكد من وجود الـ Binary قبل التشغيل لتفادي الكراش الصامت
if not os.path.exists("./xray"):
    print("[-] Critical: ./xray binary not found in current directory!", flush=True)
    sys.exit(1)

print("[*] Launching Xray Core inside container...", flush=True)
try:
    subprocess.Popen(["./xray", "-config", "config.json"])
    print("[+] Xray Core launched successfully in background.", flush=True)
except Exception as e:
    print(f"[-] Critical: Failed to start Xray Core: {e}", flush=True)
    sys.exit(1)

time.sleep(3)

print(f"[+] Monitor Daemon Started. Target VPS: {VPS_URL}", flush=True)

def get_user_traffic(email):
    try:
        payload = f'pattern: "user>>{email}" reset: false'
        cmd = [
            "./xray", "api",
            f"--server={XRAY_API_SERVER}",
            "xray.app.stats.command.StatsService.QueryStats",
            payload
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)

        if res.returncode != 0 or not res.stdout:
            return 0

        # قراءة الميڨات بدقة بالـ Regex من الـ Textproto اللّي يرجع
        values = re.findall(r'value:\s*(\d+)', res.stdout)
        if values:
            return sum(int(v) for v in values)

    except Exception as e:
        print(f"[-] Critical Error parsing traffic for {email}: {e}", flush=True)
    return 0

def report_usage(email, bytes_used):
    try:
        url = f"{VPS_URL}/report_usage"
        payload = {"email": email, "bytes": bytes_used}
        res = requests.post(url, json=payload, timeout=5)
        if res.status_code == 200:
            print(f"[+] Successfully reported {bytes_used} bytes to VPS for {email}", flush=True)
            return True
    except Exception as e:
        print(f"[-] Failed sending traffic report to VPS: {e}", flush=True)
    return False

def fetch_active_users():
    try:
        res = requests.get(f"{VPS_URL}/get_active_users", timeout=5)
        if res.status_code == 200:
            return res.json()
        print(f"[-] Failed fetching users from VPS. Code: {res.status_code}", flush=True)
        return None
    except Exception as e:
        print(f"[-] Network error fetching users from VPS: {e}", flush=True)
        return None

reported_bytes = {}
current_xray_users = set()

while True:
    print("[*] Starting Sync Cycle...", flush=True)
    active_users = fetch_active_users()

    if active_users is not None:
        active_emails = {u["email"] for u in active_users}

        # 1. إضافة المستخدمين بالـ textproto الصحيح والنهائي (add_user)
        for user in active_users:
            email = user["email"]
            uuid = user["uuid"]
            if email not in current_xray_users:
                # الفورما القياسية الصخرة اللّي يقبلها الـ Go Parser بدون مشاكل
                payload = f'tag: "vless-in" operation: {{ add_user: {{ user: {{ email: "{email}" id: "{uuid}" }} }} }}'
                cmd = [
                    "./xray", "api",
                    f"--server={XRAY_API_SERVER}",
                    "xray.app.proxyman.command.HandlerService.AlterInbound",
                    payload
                ]
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    current_xray_users.add(email)
                    print(f"[+] Successfully injected user to Xray: {email}", flush=True)
                else:
                    print(f"[-] Xray rejected injecting user {email}: {res.stderr.strip()}", flush=True)

        # 2. حساب الاستهلاك بالـ Delta الآمن
        for email in list(current_xray_users):
            xray_total = get_user_traffic(email)
            
            if xray_total > 0:
                if email not in reported_bytes:
                    reported_bytes[email] = 0
                
                if xray_total < reported_bytes[email]:
                    reported_bytes[email] = 0
                
                delta_bytes = xray_total - reported_bytes[email]
                if delta_bytes > 0:
                    if report_usage(email, delta_bytes):
                        reported_bytes[email] = xray_total

            # 3. الحظر والـ الحذف بالـ textproto الصحيح (remove_user)
            if email not in active_emails:
                payload = f'tag: "vless-in" operation: {{ remove_user: {{ email: "{email}" }} }}'
                cmd = [
                    "./xray", "api",
                    f"--server={XRAY_API_SERVER}",
                    "xray.app.proxyman.command.HandlerService.AlterInbound",
                    payload
                ]
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    current_xray_users.remove(email)
                    if email in reported_bytes:
                        del reported_bytes[email]
                    print(f"[-] Blocked and removed user from Xray: {email}", flush=True)
                else:
                    print(f"[-] Failed removing user {email}: {res.stderr.strip()}", flush=True)
    else:
        print("[!] Sync skipped - protecting current sessions.", flush=True)

    time.sleep(15)
