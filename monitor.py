import json
import subprocess
import time
import requests

API_URL = "https://try-rhon.onrender.com"

print("==> Step 1: Fetching users from Render at boot...")
active_users = []
try:
    # جلب المستخدمين النشطين فوراً عند إقلاع الحاوية
    res = requests.get(f"{API_URL}/get_active_users", timeout=12)
    if res.status_code == 200:
        active_users = res.json()
        print(f"[+] Found {len(active_users)} active users on Render.")
except Exception as e:
    print(f"[-] Boot fetch failed: {e}")

print("==> Step 2: Injecting users into config.json directly...")
try:
    with open("config.json", "r") as f:
        config = json.load(f)
    
    # تحويل الحسابات الجاهزة لـ الصيغة اللي يفهمها الـ Xray
    clients = [{"id": u["uuid"], "level": 0, "email": u["email"]} for u in active_users]
    
    # حشر الحسابات داخل المصفوفة الفارغة
    for inbound in config.get("inbounds", []):
        if inbound.get("tag") == "vless-in":
            inbound["settings"]["clients"] = clients
            
    with open("config.json", "w") as f:
        json.dump(config, f, indent=2)
    print(f"[+] Successfully prepared config.json with {len(clients)} users.")
except Exception as e:
    print(f"[-] Config patch failed: {e}")

print("==> Step 3: Launching Xray Core as sub-process...")
# تشغيل الـ Xray بالملف المحدث ديريكت
xray_proc = subprocess.Popen(["./xray", "-config", "config.json"])

print("==> Step 4: Starting background sync loop for new users...")
monitored_emails = [u["email"] for u in active_users]
time.sleep(2)

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
                "email": email, "level": 0,
                "account": { "@type": "type.googleapis.com/xray.proxy.vless.Account", "id": u_uuid }
            }
        }
    }
    cmd = ["./xray", "api", "--server=127.0.0.1:10085", "xray.app.proxyman.command.HandlerService.AlterInbound"]
    res = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True)
    return res.returncode == 0

# اللوب الدوري لتحديث البيانات ومراقبة المقصلة (50 ميجا)
while True:
    if xray_proc.poll() is not None:
        print("[-] Xray core stopped. Exiting script.")
        break
    try:
        res = requests.get(f"{API_URL}/get_active_users", timeout=10)
        if res.status_code == 200:
            for u in res.json():
                if u['email'] not in monitored_emails:
                    if add_user_dynamic(u['uuid'], u['email']):
                        monitored_emails.append(u['email'])
    except: pass

    for email in list(monitored_emails):
        usage = get_user_traffic(email)
        try:
            res = requests.post(f"{API_URL}/sync_usage", json={"email": email, "bytes": usage}, timeout=10)
            if res.status_code == 200 and res.json().get("status") == "block":
                block_user_dynamic(email)
                monitored_emails.remove(email)
        except: pass
    time.sleep(15)
