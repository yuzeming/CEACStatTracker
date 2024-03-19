FROM python:3.12-slim
WORKDIR /app

# still need curl for the ECS container health check!
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic-dev curl

COPY * /app
RUN pip3 install --no-cache-dir -r /app/requirements.txt
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="$PYTHONPATH:/app"


CMD ["/app/start.sh"]