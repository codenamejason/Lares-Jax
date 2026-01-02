FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files (README.md needed for pyproject.toml)
COPY pyproject.toml README.md ./

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Copy source code
COPY src/ src/
COPY run.py ./

# Set Python path (run.py uses sys.path.insert, but this ensures imports work)
ENV PYTHONPATH=/app/src:/app

# Run Lares bot
CMD ["python", "run.py"]
