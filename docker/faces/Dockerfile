FROM python:3.11-slim

LABEL org.opencontainers.image.description="ResourceSpace AI Faces (InsightFace) Service"

# Install system dependencies for OpenCV headless and InsightFace compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    insightface \
    onnxruntime \
    faiss-cpu \
    opencv-python-headless \
    python-multipart \
    mysql-connector-python

WORKDIR /app

# The faces_service.py will be copied from ResourceSpace checkout
# We fetch it at build time from the official SVN
RUN curl -sSL "https://svn.resourcespace.com/svn/rs/releases/10.7/plugins/faces/scripts/faces_service.py" -o faces_service.py

EXPOSE 8001

# Environment variables for database connection (FACES_ prefix used by faces_service.py)
ENV FACES_DB_HOST=mysql
ENV FACES_DB_USER=resourcespace
ENV FACES_PORT=8001

# Note: FACES_DB_PASS must be set at runtime via render.yaml
CMD ["sh", "-c", "python faces_service.py --port=$FACES_PORT"]
