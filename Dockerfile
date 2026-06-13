FROM python:3.10-slim
WORKDIR /app
RUN apt-get update && apt-get install -y unzip wget curl && rm -rf /var/lib/apt/lists/*
RUN wget https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip && unzip Xray-linux-64.zip && chmod +x xray
COPY . .
RUN pip install requests
CMD ["sh", "start.sh"]
