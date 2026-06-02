FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY examples ./examples

RUN python -m pip install --no-cache-dir .

EXPOSE 8080

CMD ["uvicorn", "strataone.api:app", "--host", "0.0.0.0", "--port", "8080"]
