from dotenv import load_dotenv
import os

# Charger les variables depuis le fichier .env
load_dotenv()


class Config:
    # Clé secrète obligatoire - pas de fallback hardcodé
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY manquante dans le fichier .env")

    # Mode debug désactivé par défaut
    DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'

    # Base de données
    MONGO_URI = os.getenv('MONGO_URI')

    # Twilio
    TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
    TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
    TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

    # Numéro du conseiller médical
    ADVISOR_PHONE_NUMBER = os.getenv('ADVISOR_PHONE_NUMBER', '+22654125637')

    # Google Gemini API
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

    # Sécurité des sessions
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 1800  # 30 minutes

    # Limite de taille des requêtes (1 MB)
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024

    # Configuration de Flask-Mail
    MAIL_SERVER = os.environ.get('MAIL_SERVER') or 'smtp.gmail.com'
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or 'woubiaziz@gmail.com'
