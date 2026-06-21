import os
import sys
import time
import json
import requests
import subprocess
import re

VPS_URL = os.getenv("VPS_URL", "http://35.171.3.190:5000")
XRAY_API_SERVER = "127.0.0.1:10085"

print("[*] Launching Xray Core inside container...", flush=True)
try:
    subprocess.Popen(["./xray", "-config", "config.json"])
    print("[+] Xray Core launched successfully in background.", flush=True)
except Exception as e:
    print(f"[-] Critical: Failed to start Xray Core: {e}", flush=True)
    sys.exit(1)

time.sleep(2)

print(f"[+] Monitor Daemon Started. Target VPS: {VPS_URL}", flush=True)

def get_user_traffic(email):
    try:
        # 🔥 رجعناها reset: False باش الـ Xray ما يمسح والو من الذاكرة وتكون الداتا محمية
        query = {"pattern": f"user>>{email}", "reset": False}
        cmd = ["./xray", "api", f"--server={XRAY_API_SERVER}", "xray.app.stats.command.StatsService.QueryStats"]
        res = subprocess.run(cmd, input=json.dumps(query), capture_output=True, text=True)

        if res.returncode != 0:
            return 0

        if not res.stdout or not res.stdout.strip():
            return 0

        output = res.stdout.strip()
        total_bytes = 0

        try:
            data = json.loads(output)
            if "stat" in data and isinstance(data["stat"], list):
                for item in data["stat"]:
                    total_bytes += int(item.get("value", 0))
                return total_bytes
        except json.JSONDecodeError:
            values = re.findall(r'value:\s*(\d+)', output)
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
            return True # نرجعو True إذا نجح الإرسال بنجاح للـ VPS
    except Exception as e:
        print(f"[-] Failed sending traffic report to VPS: {e}", flush=True)
    return False # نرجعو False إذا كاين أي مشكل أو تيم آوت

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

# 🔥 الذاكرة المحلية لحفظ آخر استهلاك تم إبلاغه للـ VPS بنجاح
reported_bytes = {}

current_xray_users = set()

while True:
    print("[*] Starting Sync Cycle...", flush=True)
    active_users = fetch_active_users()

    if active_users is not None:
        active_emails = {u["email"] for u in active_users}

        # 1. إضافة المستخدمين الجدد
        for user in active_users:
            email = user["email"]
            uuid = user["uuid"]
            if email not in current_xray_users:
                add_payload = {
                    "tag": "vless-in",
                    "operation": {
                        "type_url": "type.googleapis.com/xray.app.proxyman.command.AddUserOperation",
                        "value": {
                            "user": {
                                "email": email,
                                "id": uuid,
                                "level": 0
                            }
                        }
                    }
                }
                cmd = ["./xray", "api", f"--server={XRAY_API_SERVER}", "xray.app.proxyman.command.HandlerService.AlterInbound"]
                res = subprocess.run(cmd, input=json.dumps(add_payload), capture_output=True, text=True)
                
                if res.returncode == 0:
                    current_xray_users.add(email)
                    print(f"[+] Successfully injected user to Xray: {email}", flush=True)
                else:
                    print(f"[-] Xray rejected injecting user {email}: {res.stderr.strip()}", flush=True)

        # 2. حساب الاستهلاك بالـ Delta وحظر فوري بدون ضياع بايت واحد
        for email in list(current_xray_users):
            xray_total = get_user_traffic(email)
            
            if xray_total > 0:
                if email not in reported_bytes:
                    reported_bytes[email] = 0
                
                # حساب الـ Delta (الزيادة الجديدة برك من آخر إرسال ناجح)
                delta_bytes = xray_total - reported_bytes[email]
                
                if delta_bytes > 0:
                    # نبعثو الزيادة فقط للـ VPS، وإذا نجحت 200 OK نحدثو العداد المحلي ديريكت
                    if report_usage(email, delta_bytes):
                        reported_bytes[email] = xray_total
                        print(f"[+] Local cache updated for {email} to {xray_total} bytes", flush=True)

            if email not in active_emails:
                remove_payload = {
                    "tag": "vless-in",
                    "operation": {
                        "type_url": "type.googleapis.com/xray.app.proxyman.command.RemoveUserOperation",
                        "value": {
                            "email": email
                        }
                    }
                }
                cmd = ["./xray", "api", f"--server={XRAY_API_SERVER}", "xray.app.proxyman.command.HandlerService.AlterInbound"]
                res = subprocess.run(cmd, input=json.dumps(remove_payload), capture_output=True, text=True)
                
                if res.returncode == 0:
                    current_xray_users.remove(email)
                    if email in reported_bytes:
                        del reported_bytes[email] # تنظيف الذاكرة للمستخدم المحظور
                    print(f"[-] Blocked and removed user from Xray: {email}", flush=True)
                else:
                    print(f"[-] Failed removing user {email}: {res.stderr.strip()}", flush=True)
    else:
        print("[!] Sync skipped - protecting current sessions.", flush=True)

    time.sleep(15)
