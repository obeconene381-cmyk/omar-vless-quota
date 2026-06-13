import json
import subprocess
import time
import requests

API_URL = "https://try-rhon.onrender.com"

print("==> Step 1: Fetching users from Render at boot...")
active_users = []
try:
    res = requests.get(f"{API_URL}/get_active_users", timeout=12)
    if res.status_code == 200:
        # فلترة المستخدمين عند الإقلاع: أي واحد الكوتة تاعه 0 أو مستهلكة تماماً نطيروه وما نحقنوهش
        for u in res.json():
            quota_mb = u.get("quota_mb", 0)
            used_bytes = u.get("used_bytes", 0)
            used_mb = used_bytes / (1024 * 1024)
            if quota_mb > 0 and used_mb < quota_mb:
                active_users.append(u)
        print(f"[+] Found {len(active_users)} valid active users on Render.")
except Exception as e:
    print(f"[-] Boot fetch failed: {e}")

print("==> Step 2: Injecting users into config.json directly...")
try:
    with open("config.json", "r") as f:
        config = json.load(f)
    
    clients = [{"id": u["uuid"], "level": 0, "email": u["email"]} for u in active_users]
    
    for inbound in config.get("inbounds", []):
        if inbound.get("tag") == "vless-in":
            inbound["settings"]["clients"] = clients
            
    with open("config.json", "w") as f:
        json.dump(config, f, indent=2)
    print(f"[+] Successfully prepared config.json with {len(clients)} users.")
except Exception as e:
    print(f"[-] Config patch failed: {e}")

print("==> Step 3: Launching Xray Core...")
xray_proc = subprocess.Popen(["./xray", "-config", "config.json"])

monitored_emails = [u["email"] for u in active_users]
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
    print(f"[-] Removing/Blocking user from Xray memory: {email}")
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
    if res.returncode == 0:
        print(f"[+] Successfully injected new user: {email}")
        return True
    return False

print("==> Step 4: Entering dynamic state sync loop...")
while True:
    if xray_proc.poll() is not None:
        print("[-] Xray core crashed or stopped. Exiting.")
        break
        
    try:
        res = requests.get(f"{API_URL}/get_active_users", timeout=10)
        if res.status_code == 200:
            api_users = res.json()
            api_emails = {u['email'] for u in api_users}
            
            # أ. الفلترة والحقن الذكي للمستخدمين الجدد
            for u in api_users:
                quota_mb = u.get("quota_mb", 0)
                used_bytes = u.get("used_bytes", 0)
                used_mb = used_bytes / (1024 * 1024)
                
                # المقصلة المحلية: إذا راندر باعت مستخدم ميت (كوتة 0 أو مخلصة)، بلوكيه فوراً واحرقه
                if quota_mb <= 0 or used_mb >= quota_mb:
                    if u['email'] in monitored_emails:
                        block_user_dynamic(u['email'])
                        monitored_emails.remove(u['email'])
                    continue
                
                # إذا كان صح مستخدم حي ومكانش في المراقبة، احقنه
                if u['email'] not in monitored_emails:
                    if add_user_dynamic(u['uuid'], u['email']):
                        monitored_emails.append(u['email'])
            
            # ب. طرد أي واحد تنحى قاع من راندر
            for email in list(monitored_emails):
                if email not in api_emails:
                    block_user_dynamic(email)
                    monitored_emails.remove(email)
    except Exception as e:
        print(f"Error syncing list from Render: {e}")

    # 2. إرسال الترافيك وقراءة أمر الحظر الفوري من الـ Response
    for email in list(monitored_emails):
        usage = get_user_traffic(email)
        try:
            sync_res = requests.post(f"{API_URL}/sync_usage", json={"email": email, "bytes": usage}, timeout=10)
            # التعديل الصخرة: إذا راندر رجع status: block اقطع عليه في نفس الثانية قبالة
            if sync_res.status_code == 200 and sync_res.json().get("status") == "block":
                block_user_dynamic(email)
                monitored_emails.remove(email)
        except: pass
        
    time.sleep(15)
