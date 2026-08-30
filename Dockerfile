FROM python:3.11-slim

WORKDIR /app

# Chrome için gerekli bağımlılıklar
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    unzip \
    xvfb \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    libgbm1 \
    libnss3 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libdrm2 \
    libxkbcommon0 \
    libxshmfence1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Chrome'u doğrudan .deb ile kur (apt-key yok)
RUN curl -LO https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get update && apt-get install -y ./google-chrome-stable_current_amd64.deb \
    && rm google-chrome-stable_current_amd64.deb

# Python paketleri
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright
RUN playwright install chromium

# Uygulama
COPY main.py .
COPY accounts.txt .

CMD ["python", "main.py"]
