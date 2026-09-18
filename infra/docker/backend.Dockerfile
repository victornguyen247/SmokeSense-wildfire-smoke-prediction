FROM python:3.12-slim

# System deps for geospatial libs (GeoPandas/shapely) and psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        gdal-bin \
        libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code

# Install deps first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Overridden by docker-compose for dev (--reload); this is the prod default.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
