FROM alpine:latest

# 1. تحديث النظام وتركيب بايثون، مدير الحزم pip، والملحقات الضرورية
RUN apk update && apk add --no-cache python3 py3-pip bash curl unzip

# 2. تركيب مكتبة requests باستخدام pip
RUN pip3 install --no-cache-dir requests --break-system-packages

WORKDIR /app
COPY . .

# 3. تحميل الـ Xray Core
RUN curl -L -o xray.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip && \
    unzip xray.zip && rm xray.zip && chmod +x xray

EXPOSE 8080

# التعديل هنا: زدت -u باش اللوڨز يخرجوا لايف في نفس الملي ثانية لقوقل كلاود
CMD ["python3", "-u", "monitor.py"]
