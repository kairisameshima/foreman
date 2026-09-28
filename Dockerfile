FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN pip install poetry==2.3.1

COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false \
    && poetry install --no-root --only main --no-interaction --no-ansi

COPY foreman ./foreman

EXPOSE 8765

CMD ["sh", "-c", "uvicorn foreman.app:app --host 0.0.0.0 --port ${PORT:-8765}"]
