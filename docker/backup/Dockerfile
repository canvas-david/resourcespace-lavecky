FROM mysql:8.0

# MySQL 8 uses Oracle Linux - use microdnf instead of apt-get
RUN microdnf install -y \
    awscli \
    openssl \
    && microdnf clean all

COPY docker/backup/backup-mysql.sh /backup.sh
RUN chmod +x /backup.sh

CMD ["/backup.sh"]
