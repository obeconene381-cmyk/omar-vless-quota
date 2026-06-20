FROM alpine:latest
RUN apk add --no-cache python3 requests bash curl unzip
WORKDIR /app
COPY . .
RUN curl -L -o xray.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip && \
    unzip xray.zip && rm xray.zip && chmod +x xray
EXPOSE 8080
CMD ["python3", "monitor.py"]
