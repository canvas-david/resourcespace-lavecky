FROM ubuntu:24.04

LABEL org.opencontainers.image.authors="Montala Ltd (extended for S3/R2 support)"
LABEL org.opencontainers.image.description="ResourceSpace DAM with S3 storage plugin support"

ENV DEBIAN_FRONTEND="noninteractive"

RUN apt-get update && apt-get install -y \
    nano \
    wget \
    curl \
    ca-certificates \
    apache2 \
    libapache2-mod-php \
    php \
    php-apcu \
    php-curl \
    php-dev \
    php-gd \
    php-intl \
    php-mysqlnd \
    php-mbstring \
    php-zip \
    php-xml \
    imagemagick \
    ghostscript \
    antiword \
    poppler-utils \
    libimage-exiftool-perl \
    ffmpeg \
    subversion \
    cron \
    postfix \
    unzip \
    gettext-base \
    mysql-client \
    openssh-server \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*
# Note: OpenCV/Python removed - AI Faces runs as separate 'faces' service (InsightFace)
# Note: mysql-client added for database initialization checks
# Note: openssh-server added for Render SSH access

RUN sed -i -e "s/upload_max_filesize\s*=\s*2M/upload_max_filesize = 2G/g" /etc/php/8.3/apache2/php.ini \
 && sed -i -e "s/post_max_size\s*=\s*8M/post_max_size = 2G/g" /etc/php/8.3/apache2/php.ini \
 && sed -i -e "s/max_execution_time\s*=\s*30/max_execution_time = 600/g" /etc/php/8.3/apache2/php.ini \
 && sed -i -e "s/memory_limit\s*=\s*128M/memory_limit = 1G/g" /etc/php/8.3/apache2/php.ini \
 && sed -i -e "s/max_input_time\s*=\s*60/max_input_time = 600/g" /etc/php/8.3/apache2/php.ini

RUN printf '<Directory /var/www/>\n\
\tOptions FollowSymLinks\n\
</Directory>\n'\
>> /etc/apache2/sites-enabled/000-default.conf

RUN a2enmod rewrite headers

WORKDIR /var/www/html

RUN rm -f index.html \
 && svn co -q https://svn.resourcespace.com/svn/rs/releases/10.7 . \
 && mkdir -p filestore \
 && chmod 777 filestore \
 && chmod -R 777 include/

COPY cronjob /etc/cron.daily/resourcespace
COPY entrypoint.sh /entrypoint.sh
COPY docker/config.php.template /docker/config.php.template

RUN chmod +x /entrypoint.sh \
 && chmod +x /etc/cron.daily/resourcespace

# SSH access for Render (https://render.com/docs/ssh#docker-specific-configuration)
RUN mkdir -p /root/.ssh && chmod 0700 /root/.ssh

EXPOSE 80

CMD ["/entrypoint.sh"]
