import time
import subprocess
import json
import requests

API_URL = "https://try-rhon.onrender.com" 

# 🛑 خطة دفاعية: انتظر 5 ثوانٍ كاملة حتى يشتغل الـ Xray ويفتح البورت 10085 تماماً
print("⏳ Waiting 5 seconds for Xray core to initialize internal ports...")
time.sleep(5)

def get_user_traffic(email):
    try:
        payload = {"pattern": email, "reset": False}
        cmd = ["./xray", "api", "--server=127.0.0.1:10085", "xray.app.stats.command.StatsService.QueryStats"]
        res = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True)
        if res.returncode == 0 and res.stdout:
            data = json.loads(res.stdout)
            if "stat" in data:
                return sum(int(item.get("value", 0)) for item in data["stat"])
    except: pass
    return 0

def block_user_dynamic(email):
    print(f"[-] Blocking user traffic: {email}")
    payload = {
        "tag": "vless-in",
        "operation": {
            "@type": "type.googleapis.com/xray.app.proxyman.command.RemoveUserOperation",
            "email": email
        }
    }
    cmd = ["./xray", "api", "--server=127.0.0.1:10085", "xray.app.proxyman.command.HandlerService.AlterInbound"]
    subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True)

def add_user_dynamic(u_uuid, email):
    payload = {
        "tag": "vless-in",
        "operation": {
            "@type": "type.googleapis.com/xray.app.proxyman.command.AddUserOperation",
            "user": {
                "email": email,
                "level": 0,
                "account": {
                    "@type": "type.googleapis.com/xray.proxy.vless.Account",
                    "id": u_uuid
                }
              }
        }
    }
    cmd = ["./xray", "api", "--server=127.0.0.1:10085", "xray.app.proxyman.command.HandlerService.AlterInbound"]
    res = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True)
    
    # لا نعتبر المستخدم مفعل إلا إذا نجح الأمر داخلياً ورجع كود 0
    if res.returncode == 0:
        print(f"[+] Successfully activated user: {email} | UUID: {u_uuid}")
        return True
    else:
        print(f"❌ Failed to inject user via Xray API: {res.stderr}")
        return False

monitored_emails = []
print("-> Sync Monitor Started successfully...")

while True:
    try:
        res = requests.get(f"{API_URL}/get_active_users", timeout=15)
        if res.status_code == 200:
            all_actives = res.json()
            for u in all_actives:
                if u['email'] not in monitored_emails:
                    # محاولة الحقن، وإذا نجحت فقط نضيفه للمراقبة
                    if add_user_dynamic(u['uuid'], u['email']):
                        monitored_emails.append(u['email'])
    except Exception as e:
        print(f"Error fetching active users: {e}")

    for email in list(monitored_emails):
        usage = get_user_traffic(email)
        try:
            res = requests.post(f"{API_URL}/sync_usage", json={"email": email, "bytes": usage}, timeout=15)
            if res.status_code == 200:
                status_data = res.json()
                if status_data.get("status") == "block":
                    block_user_dynamic(email)
                    monitored_emails.remove(email)
        except Exception as e:
            print(f"Error syncing data for {email}: {e}")
            
    time.sleep(15)
