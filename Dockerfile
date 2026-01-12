FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies
# WeasyPrint needs: libpango-1.0-0 libpangoft2-1.0-0 libgdk-pixbuf-2.0-0
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    python3-cffi \
    python3-brotli \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt && pip install gunicorn

# Copy project
COPY . /app/

# Create directory for sqlite db and static files
RUN mkdir -p /app/data /app/staticfiles

# Expose port
EXPOSE 8000

# Run gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "spiz_project.wsgi:application"]
