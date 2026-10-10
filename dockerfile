FROM python:3.9-slim

WORKDIR /app
COPY . /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /app/logs /app/data
EXPOSE 5050

CMD ["python", "-u", "src/main.py"]
