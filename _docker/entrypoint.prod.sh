#!/bin/sh
set -e

export PORT="${PORT:-8080}"

mkdir -p /var/log/supervisor /var/log/nginx
envsubst '${PORT}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf

if [ -n "${APP_KEY}" ] && [ -n "${DB_HOST}" ]; then
    php artisan migrate --force --no-interaction
    php artisan config:cache
    php artisan route:cache
    php artisan view:cache
fi

exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
