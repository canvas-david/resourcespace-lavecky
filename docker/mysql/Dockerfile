FROM mysql:8.0

# Minimal safe defaults
COPY docker/mysql/my.cnf /etc/mysql/conf.d/custom.cnf

# Initialization script for users/database
COPY docker/mysql/init.sql /docker-entrypoint-initdb.d/init.sql

# Health check script
COPY docker/mysql/healthcheck.sh /healthcheck.sh
RUN chmod +x /healthcheck.sh

HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=30s \
    CMD /healthcheck.sh

EXPOSE 3306
