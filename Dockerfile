FROM python:3.10

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install chromium dependencies manually (Debian-compatible)
RUN apt-get update && apt-get install -y \
    libatk1.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
    libpangocairo-1.0-0 libnss3 libatk-bridge2.0-0 \
    libxshmfence1 libglu1-mesa

# Install Playwright and Chromium
RUN pip install playwright
RUN playwright install chromium

COPY . .

ENV QUIZ_SECRET="changeme"

CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]
