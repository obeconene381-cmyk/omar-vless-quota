FROM alpine:latest
RUN apk update && apk add --no-cache python3 py3-pip bash curl unzip
RUN pip3 install --no-cache-dir requests flask redis --break-system-packages
WORKDIR /app
COPY . .
RUN curl -L -o xray.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip && \
    unzip xray.zip && rm xray.zip && chmod +x xray
EXPOSE 8080
CMD ["python3", "-u", "monitor.py"]
