FROM python:3.11-slim
WORKDIR /app
# Install system dependencies for pikepdf
RUN apt-get update && apt-get install -y \
    libqpdf-dev \
    qpdf \
    gcc \
    g++ \
    libjpeg-dev \
    zlib1g-dev \
    ghostscript \
    && rm -rf /var/lib/apt/lists/*
# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Copy application code
COPY app.py .
# Run with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--timeout", "120", "app:app"]
