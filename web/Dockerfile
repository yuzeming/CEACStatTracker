FROM --platform=arm64 python:3.12-slim
WORKDIR /app
COPY * /app
RUN pip3 install --no-cache-dir -r /app/requirements.txt

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="$PYTHONPATH:/app"


CMD ["/app/start.sh"]