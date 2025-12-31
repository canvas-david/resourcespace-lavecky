FROM mysql:8.0

RUN apt-get update && apt-get install -y \
    awscli \
    openssl \
    && rm -rf /var/lib/apt/lists/*

COPY backup-mysql.sh /backup.sh
RUN chmod +x /backup.sh

CMD ["/backup.sh"]
