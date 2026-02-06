# Chess Engine Service Dockerfile
# Multi-engine server: LC0, Stockfish, Maia

# Stage 1: Build LC0
FROM nvidia/cuda:12.2.2-cudnn8-devel-ubuntu22.04 AS lc0-builder

ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    ninja-build \
    python3 \
    python3-pip \
    libopenblas-dev \
    zlib1g-dev \
    libgtest-dev \
    && pip3 install meson \
    && rm -rf /var/lib/apt/lists/*

# Clone and build LC0
WORKDIR /build
RUN git clone --depth 1 --branch v0.31.2 https://github.com/LeelaChessZero/lc0.git \
    && cd lc0 \
    && git submodule update --init --recursive \
    && ./build.sh

# Stage 2: Runtime image
FROM nvidia/cuda:12.2.2-cudnn8-runtime-ubuntu22.04

LABEL maintainer="SeasGroup"
LABEL description="Multi-engine chess service: LC0, Stockfish, Maia"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    python3-pip \
    wget \
    curl \
    ca-certificates \
    libopenblas0 \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.11 as default
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# ========== LC0 ==========
COPY --from=lc0-builder /build/lc0/build/release/lc0 /opt/lc0/lc0
RUN chmod +x /opt/lc0/lc0

ENV PATH="/opt/lc0:/opt/stockfish:${PATH}"
ENV LC0_PATH=/opt/lc0/lc0

# ========== Stockfish ==========
# Download latest Stockfish (v16.1)
RUN mkdir -p /opt/stockfish \
    && curl -sL "https://github.com/official-stockfish/Stockfish/releases/download/sf_16.1/stockfish-ubuntu-x86-64-avx2.tar" \
    | tar -xf - -C /opt/stockfish --strip-components=1 \
    && chmod +x /opt/stockfish/stockfish-ubuntu-x86-64-avx2 \
    && ln -sf /opt/stockfish/stockfish-ubuntu-x86-64-avx2 /opt/stockfish/stockfish \
    && ls -la /opt/stockfish/

ENV STOCKFISH_PATH=/opt/stockfish/stockfish

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ========== Neural Networks ==========
RUN mkdir -p /app/networks

# Download LC0 network (BT4-1024x15x32h-swa-6147500, ~320MB)
RUN curl -sL "https://storage.lczero.org/files/networks-contrib/big-transformers/BT4-1024x15x32h-swa-6147500.pb.gz" \
    -o /app/networks/BT4.pb.gz \
    && ls -la /app/networks/BT4.pb.gz

# Download Maia network (maia-1900, strongest human-like model)
RUN curl -sL "https://github.com/CSSLab/maia-chess/releases/download/v1.0/maia-1900.pb.gz" \
    -o /app/networks/maia-1900.pb.gz \
    && ls -la /app/networks/maia-1900.pb.gz

ENV LC0_NETWORK=/app/networks/BT4.pb.gz
ENV MAIA_NETWORK=/app/networks/maia-1900.pb.gz

# Copy application code
COPY src/ ./src/
COPY gunicorn.conf.py .

# Environment defaults
ENV HOST=0.0.0.0
ENV PORT=8001
ENV DEBUG=false

# LC0 config
ENV LC0_BACKEND=cuda-fp16
ENV LC0_GPU_IDS=0
ENV LC0_HASH_MB=2048
ENV LC0_THREADS=2

# Stockfish config
ENV STOCKFISH_HASH_MB=2048
ENV STOCKFISH_THREADS=4
ENV STOCKFISH_ENABLED=true

# Maia config
ENV MAIA_ENABLED=true

# Analysis defaults
ENV DEFAULT_NODES=100000
ENV DEFAULT_NUM_MOVES=10
ENV DEFAULT_DEPTH=20

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD wget -q --spider http://localhost:${PORT}/health || exit 1

EXPOSE 8001

CMD ["gunicorn", "src.main:app", "-c", "gunicorn.conf.py"]
