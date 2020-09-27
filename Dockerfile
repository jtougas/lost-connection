FROM ubuntu:20.04

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-dev \
        python3-pip \
        openssh-server

RUN mkdir /var/run/sshd
RUN echo 'root:THEPASSWORDYOUCREATED' | chpasswd
RUN sed -i 's/#*PermitRootLogin prohibit-password/PermitRootLogin yes/g' /etc/ssh/sshd_config

WORKDIR /src

COPY requirements.txt .
RUN python3 -m pip install -r requirements.txt

COPY docker-entrypoint.sh .
COPY prog.py .

ENTRYPOINT ["/src/docker-entrypoint.sh"] 