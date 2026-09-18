FROM python:3.12-slim

# Same base as backend — worker runs ingestion + feature/ML code and shares deps.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        gdal-bin \
        libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Runs the scheduled ingestion tasks. --beat included for periodic scheduling;
# split beat into its own service if you later scale workers horizontally.
CMD ["celery", "-A", "ingestion.tasks", "worker", "--beat", "--loglevel=info"]
