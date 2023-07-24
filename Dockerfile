FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DOCKER_BUILDKIT=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends --allow-unauthenticated \
    wget libcurl4 openssl liblzma5 supervisor \
    python3-pip python3-dev python3-setuptools build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN wget https://fastdl.mongodb.org/linux/mongodb-linux-x86_64-ubuntu2204-6.0.8.tgz \
    && mkdir -p /app/mongodb \
    && tar -C /app/mongodb -zxvf mongodb-linux-x86_64-ubuntu2204-6.0.8.tgz --strip-components=1  \
    && ln -s  /app/mongodb/bin/* /usr/local/bin/ \
    && rm mongodb-linux-x86_64-ubuntu2204-6.0.8.tgz

COPY supervisord.conf /etc/supervisor/supervisord.conf
COPY web /app/web
RUN pip3 install --no-cache-dir -r /app/web/requirements.txt
