import os
import sys
import time
import json
import requests
import subprocess
import re

VPS_URL = os.getenv("VPS_URL", "http://35.171.3.190:5000")
XRAY_API_SERVER = "127.0.0.1:10085"

print(f"[+] Monitor Daemon Started. Target VPS: {VPS_URL}", flush=True)

def get_user_traffic(email):
    try:
        # استعمال QueryStats بـ pattern يجيب الـ Uplink والـ Downlink في سطر واحد وبأقل استهلاك CPU
        cmd = f'./xray api --server={XRAY_API_SERVER} xray.app.stats.command.StatsService.QueryStats \'pattern: "user>>{email}" reset: true\''
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if res.returncode != 0:
            if res.stderr:
                print(f"[-] Xray API Stats Error for {email}: {res.stderr.strip()}", flush=True)
            return 0
            
        if not res.stdout or not res.stdout.strip():
            return 0

        output = res.stdout.strip()
        total_bytes = 0

        # المحاولة 1: إذا كان المخرج تع الـ Xray عبارة عن JSON مريڨل
        try:
            data = json.loads(output)
            if "stat" in data and isinstance(data["stat"], list):
                for item in data["stat"]:
                    total_bytes += int(item.get("value", 0))
                if total_bytes > 0:
                    print(f"[+] Traffic detected (JSON) for {email}: {total_bytes} bytes", flush=True)
                return total_bytes
        except json.JSONDecodeError:
            # المحاولة 2: إذا كان المخرج عبارة عن text-proto (value: 12345) نلقطوه بالـ Regex
            values = re.findall(r'value:\s*(\d+)', output)
            if values:
                total_bytes = sum(int(v) for v in values)
                print(f"[+] Traffic detected (Regex) for {email}: {total_bytes} bytes", flush=True)
                return total_bytes
                
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
        else:
            print(f"[-] VPS refused stats with code {res.status_code} for {email}", flush=True)
    except Exception as e:
        print(f"[-] Failed sending traffic report to VPS: {e}", flush=True)

def fetch_active_users():
    try:
        res = requests.get(f"{VPS_URL}/get_active_users", timeout=5)
        if res.status_code == 200:
            return res.json()
        print(f"[-] Failed fetching users from VPS. Code: {res.status_code}", flush=True)
        return None  # نرجع None باش نفرقو بين الغلطة وبين السيرفر الفارغ بالصح
    except Exception as e:
        print(f"[-] Network error fetching users from VPS: {e}", flush=True)
        return None

current_xray_users = set()

while True:
    print("[*] Starting Sync Cycle...", flush=True)
    active_users = fetch_active_users()
    
    # حماية: إذا صرى بڨ في جلب المستخدمين مانحذفوش الناس ديجا شغالين
    if active_users is not None:
        active_emails = {u["email"] for u in active_users}

        # 1. إضافة المستخدمين الجدد (المصلوح لي كان ديجا يمشي وملمسناهش)
        for user in active_users:
            email = user["email"]
            uuid = user["uuid"]
            if email not in current_xray_users:
                cmd = f'./xray api --server={XRAY_API_SERVER} xray.app.proxyman.command.HandlerService.AlterInbound \'tag: "vless-in" operation: ADD_USER value: {{ "user": {{ "email": "{email}", "id": "{uuid}" }} }}\''
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                if res.returncode == 0:
                    current_xray_users.add(email)
                    print(f"[+] Successfully injected user to Xray: {email}", flush=True)
                else:
                    print(f"[-] Xray rejected injecting user {email}: {res.stderr}", flush=True)

        # 2. حساب الاستهلاك + الحظر ذكي ديريكت
        for email in list(current_xray_users):
            bytes_used = get_user_traffic(email)
            if bytes_used > 0:
                report_usage(email, bytes_used)

            # الحظر يصرا فقط إذا كان السيرفر شغال ورسمي الإيميل مش لداخل القائمة النشطة
            if email not in active_emails:
                cmd = f'./xray api --server={XRAY_API_SERVER} xray.app.proxyman.command.HandlerService.AlterInbound \'tag: "vless-in" operation: REMOVE_USER value: "{email}"\''
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                if res.returncode == 0:
                    current_xray_users.remove(email)
                    print(f"[-] Blocked and removed user from Xray memory: {email}", flush=True)
                else:
                    print(f"[-] Failed removing user {email} from Xray memory: {res.stderr}", flush=True)
    else:
        print("[!] Sync skipped to protect current sessions from transient network timeout.", flush=True)

    time.sleep(15)
