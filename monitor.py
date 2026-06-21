import os, sys, time, json, requests, subprocess

VPS_URL = os.getenv("VPS_URL", "http://35.171.3.190:5000")

# 1. تشغيل الـ Xray بدون تعقيدات
print("[*] Launching Xray Core...", flush=True)
subprocess.Popen(["./xray", "-config", "config.json"])
time.sleep(3)

def run_api_cmd(cmd_name, payload):
    # الفرزة هنا: حذفنا --server نهائياً باش ما يخرجش unknown command
    # الاستدعاء المباشر عبر الـ stdin هو الأضمن
    return subprocess.run(["./xray", "api", cmd_name], input=json.dumps(payload), capture_output=True, text=True)

current_users = set()

while True:
    try:
        users = requests.get(f"{VPS_URL}/get_active_users", timeout=5).json()
        active_emails = {u["email"] for u in users}

        # إضافة المستخدمين (بدون فلاغات)
        for user in users:
            if user["email"] not in current_users:
                payload = {
                    "tag": "vless-in",
                    "operation": {
                        "@type": "type.googleapis.com/xray.app.proxyman.command.AddUserOperation",
                        "user": {"email": user["email"], "id": user["uuid"], "level": 0}
                    }
                }
                res = run_api_cmd("HandlerService.AlterInbound", payload)
                if res.returncode == 0:
                    current_users.add(user["email"])
                    print(f"[+] Inject: {user['email']}")
        
        # تنظيف المستخدمين المنتهين
        for email in list(current_users):
            if email not in active_emails:
                payload = {
                    "tag": "vless-in",
                    "operation": {
                        "@type": "type.googleapis.com/xray.app.proxyman.command.RemoveUserOperation",
                        "email": email
                    }
                }
                res = run_api_cmd("HandlerService.AlterInbound", payload)
                if res.returncode == 0:
                    current_users.remove(email)
                    print(f"[-] Removed: {email}")

    except Exception as e:
        print(f"[!] Error: {e}")
    
    time.sleep(20)
