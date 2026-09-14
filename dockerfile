FROM python:3.9-slim

WORKDIR /app
COPY . /app
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt
# Switching needs a real browser login: the Octopus enrolment API accepts a website
# session and refuses API keys and OAuth tokens alike.
#
# The libraries are listed by hand because `playwright install --with-deps` assumes
# Ubuntu package names and fails on Debian. The launch at the end is the check that
# the list is complete, so a missing library breaks the build rather than the first
# login attempt months later.
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 \
        libcairo2 libcups2 libdbus-1-3 libdrm2 libexpat1 libgbm1 libglib2.0-0 \
        libnspr4 libnss3 libpango-1.0-0 libx11-6 libxcb1 libxcomposite1 \
        libxdamage1 libxext6 libxfixes3 libxkbcommon0 libxrandr2 \
    && playwright install chromium \
    && python -c "from playwright.sync_api import sync_playwright;\
p = sync_playwright().start(); b = p.chromium.launch(); b.close(); p.stop();\
print('chromium launches')" \
    && apt-get purge -y --auto-remove && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /app/logs /app/data
EXPOSE 5050

CMD ["python", "-u", "src/main.py"]
