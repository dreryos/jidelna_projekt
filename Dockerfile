FROM python:3.15-rc-alpine3.23

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies
# WeasyPrint needs: pango, gdk-pixbuf, cairo
RUN apk add --no-cache \
    build-base \
    python3-dev \
    libffi-dev \
    pango \
    gdk-pixbuf \
    cairo \
    shared-mime-info

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
