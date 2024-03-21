FROM --platform=linux/amd64 python:3.12

# still need curl for the ECS container health check!
RUN apt update \
    && apt install -y --no-install-recommends libmagic-dev curl

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

COPY * /app/
COPY static /app/static
COPY templates /app/templates

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="$PYTHONPATH:/app"

CMD ["/app/start.sh"]