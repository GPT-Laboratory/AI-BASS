#!/bin/sh
envsubst '$BASE_URL' < /etc/nginx/nginx.template > /etc/nginx/nginx.conf
nginx -g 'daemon off;'