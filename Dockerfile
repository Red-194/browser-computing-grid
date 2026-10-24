# ── Browser Computing Grid – Controller ─────────────────────────────────────
# The WASM runtime is already pre-built and checked in at runtime/pkg/.
# No Rust toolchain is required inside the image.
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

# Metadata
LABEL org.opencontainers.image.title="Browser Computing Grid"
LABEL org.opencontainers.image.description="Zero-install browser-native distributed computing controller"
LABEL org.opencontainers.image.source="https://github.com/your-org/browser-computing-grid"

# Keep Python from writing .pyc files to disk and from buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python dependencies first (leverages layer cache on re-builds)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project
COPY app/       ./app/
COPY runtime/   ./runtime/

# Expose the controller port
EXPOSE 8000

# Run with uvicorn; --host 0.0.0.0 makes the port reachable from outside the container
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
