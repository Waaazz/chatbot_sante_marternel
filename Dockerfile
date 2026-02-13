FROM python:3.11-slim

# Variables d'environnement
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copier et installer les dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Télécharger le modèle SpaCy français
RUN python -m spacy download fr_core_news_sm

# Copier le code source
COPY . .

# Port d'écoute
EXPOSE 8000

# Commande de démarrage
CMD ["gunicorn", "-c", "gunicorn_config.py", "wsgi:app"]
