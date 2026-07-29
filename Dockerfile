FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md CHANGELOG.md LICENSE requirements-constraints.txt ./
COPY src ./src
COPY examples ./examples

RUN python -m pip install --no-cache-dir -c requirements-constraints.txt .
RUN useradd --create-home --shell /usr/sbin/nologin strataone \
    && mkdir -p /app/.strataone \
    && chown -R strataone:strataone /app/.strataone

EXPOSE 8080

USER strataone

CMD ["uvicorn", "strataone.api:app", "--host", "0.0.0.0", "--port", "8080"]
