"""
Point d'entrée WSGI pour le déploiement en production.
Usage: gunicorn -c gunicorn_config.py wsgi:app
"""
from app import app

if __name__ == "__main__":
    app.run()
