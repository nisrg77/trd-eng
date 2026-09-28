# Dockerfile.rl — Isolated Heavy PyTorch / Gymnasium / Streamlit Container for TRDENG RL Subsystem
FROM python:3.11

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch, Gym, Stable-Baselines3, Streamlit, ONNX
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy repository content
COPY . /app/

# Expose Streamlit Dashboard Port
EXPOSE 8501

# Volume mount point for ONNX candidate model exports
VOLUME ["/app/model_weights", "/app/middleware"]

# Default entrypoint starts both the 24/7 Trainer daemon and the Streamlit UI via a runner
CMD ["streamlit", "run", "research/rl/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
