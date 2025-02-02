FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "scheduler.py"]