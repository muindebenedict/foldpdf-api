FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y \
    libqpdf-dev \
    qpdf \
    gcc \
    g++ \
    libjpeg-dev \
    zlib1g-dev \
    ghostscript \
    libreoffice \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--timeout", "120", "app:app"]
