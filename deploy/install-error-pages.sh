#!/usr/bin/env bash
# Installs static assets only; preserves live domain/TLS configuration.
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$EUID" -ne 0 ]]; then
    echo "Run with sudo bash deploy/install-error-pages.sh" >&2
    exit 1
fi
install -d -m 755 /var/www/ddoc-errors/assets /etc/nginx/snippets
install -m 644 "$APP_DIR/deploy/error-pages/unavailable.html" /var/www/ddoc-errors/unavailable.html
install -m 644 "$APP_DIR/app/static/logo-ekkasan.png" /var/www/ddoc-errors/assets/logo.png
install -m 644 "$APP_DIR/app/static/fonts/Prompt-Regular.ttf" /var/www/ddoc-errors/assets/Prompt-Regular.ttf
install -m 644 "$APP_DIR/app/static/fonts/Prompt-SemiBold.ttf" /var/www/ddoc-errors/assets/Prompt-SemiBold.ttf
install -m 644 "$APP_DIR/deploy/nginx-error-pages.conf" /etc/nginx/snippets/ddoc-error-pages.conf
echo "Installed static error page. Add this once INSIDE the app's server {} block (HTTPS too):"
echo "    include /etc/nginx/snippets/ddoc-error-pages.conf;"
echo "Then run: sudo nginx -t && sudo systemctl reload nginx"
