import os
import json
import time
import subprocess
import requests

VPS_URL = os.environ.get("VPS_URL", "http://127.0.0.1:5000")
CONFIG_PATH = "config.json"
XRAY_API_SERVER = "127.0.0.1:10085"

print(f"[+] Booting Cloud Run Core. Targeted VPS Backend: {VPS_URL}")

# 1. جلب المستخدمين عند الإقلاع
active_users = []
try:
    res = requests.get(f"{VPS_URL}/get_active_users", timeout=10)
    if res.status_code == 200:
        active_users = res.json()
        print(f"[+] Loaded {len(active_users)} active users from VPS at boot.")
except Exception as e:
    print(f"[-] Boot fetch failed: {e}")

# 2. حقن إعدادات المستخدمين الأوائل في الكود
try:
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    clients = [{"id": u["uuid"], "level": 0, "email": u["email"]} for u in active_users]
    for inbound in config.get("inbounds", []):
        if inbound.get("tag") == "vless-in":
            inbound["settings"]["clients"] = clients
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    print("[+] Initial config patched successfully.")
except Exception as e:
    print(f"[-] Initial config patch error: {e}")

# 3. إطلاق الـ Xray Core
print("[+] Launching Xray core engine...")
xray_proc = subprocess.Popen(["./xray", "-config", CONFIG_PATH])

# مصفوفة المراقبة المحلية لـ الحسابات
monitored_emails = {u["email"]: u["uuid"] for u in active_users}
time.sleep(5)  # وقت آمن لفتح بورت الـ API لداخل

def get_user_traffic(email):
    try:
        # نظام الـ Delta: نلقط الاستهلاك تع الآخر 10 ثواني برك ونصفر
        payload = {"pattern": email, "reset": True}
        cmd = ["./xray", "api", f"--server={XRAY_API_SERVER}", "xray.app.stats.command.StatsService.QueryStats"]
        res = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True)
        if res.returncode == 0 and res.stdout:
            data = json.loads(res.stdout)
            if "stat" in data:
                return sum(int(item.get("value", 0)) for item in data["stat"])
    except: pass
    return 0

def block_user_instantly(email):
    print(f"[-] [Block Action] Removing user from Xray memory: {email}")
    payload = {
        "tag": "vless-in",
        "operation": {
            "@type": "type.googleapis.com/xray.app.proxyman.command.RemoveUserOperation",
            "email": email
        }
    }
    cmd = ["./xray", "api", f"--server={XRAY_API_SERVER}", "xray.app.proxyman.command.HandlerService.AlterInbound"]
    subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True)

def add_user_instantly(email, uuid_str):
    print(f"[+] [Add Action] Injecting new user dynamically into Xray: {email}")
    payload = {
        "tag": "vless-in",
        "operation": {
            "@type": "type.googleapis.com/xray.app.proxyman.command.AddUserOperation",
            "user": {
                "email": email, "level": 0,
                "account": { "@type": "type.googleapis.com/xray.proxy.vless.Account", "id": uuid_str }
            }
        }
    }
    cmd = ["./xray", "api", f"--server={XRAY_API_SERVER}", "xray.app.proxyman.command.HandlerService.AlterInbound"]
    subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True)

loop_count = 0
print("[+] Dynamic core loops engaged successfully.")

while True:
    if xray_proc.poll() is not None:
        print("[-] Xray core stopped unexpectedly. Exiting container.")
        break
    
    # أ. دورة حساب الميڨات (كل 10 ثواني)
    for email in list(monitored_emails.keys()):
        usage_bytes = get_user_traffic(email)
        if usage_bytes > 0:
            try:
                response = requests.post(f"{VPS_URL}/report_usage", json={"email": email, "bytes": usage_bytes}, timeout=5)
                # إذا الـ VPS لقى المستخدم خلص، اقطع عليه في أجزاء تع الثانية قبالة
                if response.status_code == 200 and response.json().get("status") == "block":
                    block_user_instantly(email)
                    if email in monitored_emails: del monitored_emails[email]
            except Exception as e:
                print(f"[-] Traffic report error for {email}: {e}")
                
    # ب. دورة تحديث القائمة الخلفية (كل 30 ثانية تعس الـ VPS قبالة)
    loop_count += 1
    if loop_count >= 3:
        loop_count = 0
        try:
            res = requests.get(f"{VPS_URL}/get_active_users", timeout=5)
            if res.status_code == 200:
                vps_users = res.json()
                vps_emails = {u["email"] for u in vps_users}
                
                # إضافة المشتركين الجدد لي تزادو فالبوت درك
                for u in vps_users:
                    if u["email"] not in monitored_emails:
                        add_user_instantly(u["email"], u["uuid"])
                        monitored_emails[u["email"]] = u["uuid"]
                        
                # طرد الحسابات لي تبلوكات ولا تحذفت يدوياً من البوت
                for email in list(monitored_emails.keys()):
                    if email not in vps_emails:
                        block_user_instantly(email)
                        del monitored_emails[email]
        except Exception as e:
            print(f"[-] Background sync loop error: {e}")
            
    time.sleep(10)
