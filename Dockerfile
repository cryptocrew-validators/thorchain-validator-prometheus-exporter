FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the exporter script
COPY exporter.py .

# Create non-root user
RUN useradd -m -u 1000 thorchain && \
    chown -R thorchain:thorchain /app

USER thorchain

# Expose metrics port
EXPOSE 9809

# Set default entrypoint
ENTRYPOINT ["python3", "exporter.py"]

# Default arguments (can be overridden)
CMD ["--listen", "0.0.0.0", "--port", "9809"]
