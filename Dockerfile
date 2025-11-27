FROM python:3.10

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN apt-get update && apt-get install -y \
    wget gnupg libnss3 libatk1.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2

RUN pip install playwright
RUN playwright install --with-deps chromium

COPY . .

ENV QUIZ_SECRET="changeme"

CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]
