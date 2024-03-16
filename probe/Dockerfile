FROM python:3.10
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
EXPOSE 9000
ENTRYPOINT [ "python3", "/app/index.py" ]