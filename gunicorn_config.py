"""
Configuration Gunicorn pour le déploiement en production.
Usage: gunicorn -c gunicorn_config.py wsgi:app
"""
import multiprocessing
import os

# Adresse et port (Render fournit la variable PORT)
port = os.getenv("PORT", "8000")
bind = os.getenv("GUNICORN_BIND", f"0.0.0.0:{port}")

# Nombre de workers (limité à 2 pour les tiers gratuits type Render)
workers = int(os.getenv("WEB_CONCURRENCY", os.getenv("GUNICORN_WORKERS", 2)))

# Type de worker
worker_class = "gthread"

# Threads par worker
threads = int(os.getenv("GUNICORN_THREADS", 2))

# Timeout en secondes
timeout = int(os.getenv("GUNICORN_TIMEOUT", 120))

# Taille max des requêtes (1 MB)
limit_request_body = 1048576

# Logging
accesslog = os.getenv("GUNICORN_ACCESS_LOG", "-")
errorlog = os.getenv("GUNICORN_ERROR_LOG", "-")
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")

# Redémarrage automatique des workers
max_requests = 1000
max_requests_jitter = 50

# Préchargement de l'application
preload_app = True
