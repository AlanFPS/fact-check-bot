FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv \
    && useradd --create-home --shell /bin/sh bot

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

RUN uv pip install --system -e .

USER bot
RUN mkdir -p /home/bot/data

CMD ["fact-check-bot"]
