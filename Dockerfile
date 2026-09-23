FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PYTHONPATH=/app

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the backend source code
COPY . /app/

# Expose the API port
EXPOSE 8000

# Start script using pm2 or direct python (We will use direct python in Docker for the WS server)
# CMD will be overridden in docker-compose.yml for different services
CMD ["python", "services/ws_server.py"]
