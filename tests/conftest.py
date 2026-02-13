import pytest
import os
from unittest.mock import patch, MagicMock

# Définir les variables d'environnement avant d'importer l'app
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-testing-only')
os.environ.setdefault('MONGO_URI', 'mongodb://localhost:27017/chatbot_test')
os.environ.setdefault('DEBUG', 'False')


@pytest.fixture
def mock_mongo():
    """Mock les collections MongoDB."""
    with patch('app.MongoClient') as mock_client:
        mock_db = MagicMock()
        mock_client.return_value.__getitem__ = MagicMock(return_value=mock_db)

        mock_users = MagicMock()
        mock_conversations = MagicMock()
        mock_reminders = MagicMock()

        mock_db.__getitem__ = MagicMock(side_effect=lambda name: {
            'users': mock_users,
            'conversations': mock_conversations,
            'reminders': mock_reminders
        }.get(name, MagicMock()))

        yield {
            'users': mock_users,
            'conversations': mock_conversations,
            'reminders': mock_reminders
        }


@pytest.fixture
def app():
    """Créer une instance de l'application pour les tests."""
    # Mock spacy et genai avant l'import
    with patch('spacy.load') as mock_spacy, \
         patch('app.genai') as mock_genai:
        mock_spacy.return_value = MagicMock()
        mock_genai.Client.return_value = MagicMock()

        from app import app as flask_app
        flask_app.config['TESTING'] = True
        flask_app.config['WTF_CSRF_ENABLED'] = False
        yield flask_app


@pytest.fixture
def client(app):
    """Créer un client de test Flask."""
    return app.test_client()


@pytest.fixture
def logged_in_client(client):
    """Client de test avec une session utilisateur connectée."""
    with client.session_transaction() as sess:
        sess['user_id'] = '507f1f77bcf86cd799439011'
        sess['username'] = 'testuser'
    return client


@pytest.fixture
def admin_client(client):
    """Client de test avec une session admin."""
    with client.session_transaction() as sess:
        sess['user_id'] = '507f1f77bcf86cd799439012'
        sess['username'] = 'admin'
        sess['is_admin'] = True
    return client
