FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

COPY * /app/
COPY static /app/static
COPY templates /app/templates

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="$PYTHONPATH:/app"

CMD ["python3", "-m", "flask", "run", "--host=0.0.0.0", "--port=9000"]