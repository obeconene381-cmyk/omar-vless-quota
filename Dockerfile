FROM alpine:latest

RUN apk add --no-cache python3 py3-requests bash curl

WORKDIR /app

COPY xray /app/xray
COPY config.json /app/config.json
COPY monitor.py /app/monitor.py

RUN chmod +x /app/xray

# حظر الـ buffering لضمان خروج الكود لايف للتيرمينال
ENV PYTHONUNBUFFERED=1

RUN echo $'#!/bin/bash\n\
./xray -config config.json &\n\
sleep 2\n\
python3 -u monitor.py\n\
' > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

CMD ["/app/entrypoint.sh"]
