FROM python:3.12-slim

WORKDIR /app

# System deps required by rasterio's binary wheel
RUN apt-get update && apt-get install -y --no-install-recommends \
    libexpat1 \
  && rm -rf /var/lib/apt/lists/*

# uv for fast installs
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml .
COPY src/ src/

# Install with binary wheels (rasterio/shapely/pyproj bundle GDAL/GEOS/PROJ)
RUN uv pip install --system --no-cache .

# EFS mount point for DuckDB persistence
RUN mkdir -p /data

ENV DUCKDB_PATH=/data/location_sentinel.duckdb
ENV ENV=production

EXPOSE 8000

# Single worker only -- DuckDB cannot handle multiple writers
CMD ["uvicorn", "location_sentinel.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
