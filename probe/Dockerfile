FROM --platform=linux/amd64 python:3.12-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
EXPOSE 9000
ENTRYPOINT [ "python3", "/app/index.py" ]