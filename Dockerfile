FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY Lab/requirements.txt /app/Lab/requirements.txt
RUN python -m pip install --upgrade pip && pip install -r /app/Lab/requirements.txt

COPY . /app

WORKDIR /app/Lab

EXPOSE 8080

CMD ["python", "main.py"]
