FROM python:3.9-slim

WORKDIR /app
COPY . /app
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt
# Switching needs a real browser login: the Octopus enrolment API accepts a website
# session and refuses API keys and OAuth tokens alike.
RUN playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /app/logs /app/data
EXPOSE 5050

CMD ["python", "-u", "src/main.py"]
