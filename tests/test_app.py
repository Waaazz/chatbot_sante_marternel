"""
Tests unitaires pour les routes principales de l'application.
Exécuter avec : pytest tests/ -v
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from bson import ObjectId
import os

# Variables d'environnement pour les tests
os.environ['SECRET_KEY'] = 'test-secret-key-for-testing-only'
os.environ['MONGO_URI'] = 'mongodb://localhost:27017/chatbot_test'


class TestPublicRoutes:
    """Tests pour les routes publiques (sans authentification)."""

    def test_home_page(self, client):
        """La page d'accueil doit retourner 200."""
        response = client.get('/')
        assert response.status_code == 200

    def test_login_page(self, client):
        """La page de connexion doit retourner 200."""
        response = client.get('/login')
        assert response.status_code == 200

    def test_register_page(self, client):
        """La page d'inscription doit retourner 200."""
        response = client.get('/register')
        assert response.status_code == 200

    def test_forgot_password_page(self, client):
        """La page mot de passe oublié doit retourner 200."""
        response = client.get('/forgot_password')
        assert response.status_code == 200

    def test_404_page(self, client):
        """Une URL inexistante doit retourner 404 avec une page personnalisée."""
        response = client.get('/page-inexistante')
        assert response.status_code == 404
        assert b'404' in response.data
        assert b'Page non trouv' in response.data


class TestAuthRoutes:
    """Tests pour les routes d'authentification."""

    def test_login_requires_credentials(self, client):
        """POST /login sans données doit rediriger."""
        response = client.post('/login', data={}, follow_redirects=False)
        assert response.status_code == 302

    @patch('app.users_collection')
    def test_login_wrong_password(self, mock_users, client):
        """Un mauvais mot de passe doit rediriger vers login."""
        mock_users.find_one.return_value = None
        response = client.post('/login', data={
            'username': 'testuser',
            'password': 'wrongpassword'
        }, follow_redirects=True)
        assert response.status_code == 200

    @patch('app.users_collection')
    def test_register_missing_fields(self, mock_users, client):
        """L'inscription sans champs requis doit rediriger."""
        response = client.post('/register', data={
            'username': '',
            'email': '',
            'password': '',
            'confirm_password': ''
        }, follow_redirects=True)
        assert response.status_code == 200

    @patch('app.users_collection')
    def test_register_invalid_email(self, mock_users, client):
        """L'inscription avec un email invalide doit échouer."""
        response = client.post('/register', data={
            'username': 'testuser',
            'email': 'invalid-email',
            'password': 'password123',
            'confirm_password': 'password123'
        }, follow_redirects=True)
        assert response.status_code == 200

    @patch('app.users_collection')
    def test_register_password_mismatch(self, mock_users, client):
        """L'inscription avec des mots de passe différents doit échouer."""
        response = client.post('/register', data={
            'username': 'testuser',
            'email': 'test@example.com',
            'password': 'password123',
            'confirm_password': 'different123'
        }, follow_redirects=True)
        assert response.status_code == 200

    @patch('app.users_collection')
    def test_register_short_password(self, mock_users, client):
        """L'inscription avec un mot de passe court doit échouer."""
        response = client.post('/register', data={
            'username': 'testuser',
            'email': 'test@example.com',
            'password': 'short',
            'confirm_password': 'short'
        }, follow_redirects=True)
        assert response.status_code == 200

    def test_logout(self, client):
        """La déconnexion doit rediriger vers l'accueil."""
        response = client.get('/logout', follow_redirects=False)
        assert response.status_code == 302


class TestProtectedRoutes:
    """Tests pour les routes protégées (nécessitent une connexion)."""

    def test_chat_page_requires_login(self, client):
        """La page chat doit rediriger vers login si non connecté."""
        response = client.get('/ask', follow_redirects=False)
        assert response.status_code == 302

    def test_chat_page_accessible_when_logged_in(self, logged_in_client):
        """La page chat doit être accessible quand connecté."""
        response = logged_in_client.get('/ask')
        assert response.status_code == 200

    def test_profile_requires_login(self, client):
        """La page profil doit rediriger vers login si non connecté."""
        response = client.get('/profile', follow_redirects=False)
        assert response.status_code == 302

    def test_add_reminder_requires_login(self, client):
        """La page rappel doit rediriger vers login si non connecté."""
        response = client.get('/add_reminder', follow_redirects=False)
        assert response.status_code == 302

    def test_contact_requires_login(self, client):
        """La page contact doit rediriger vers login si non connecté."""
        response = client.get('/contact', follow_redirects=False)
        assert response.status_code == 302


class TestChatAPI:
    """Tests pour l'API du chatbot."""

    def test_chat_requires_message(self, logged_in_client):
        """POST /chat sans message doit retourner 400."""
        response = logged_in_client.post('/chat',
            json={},
            content_type='application/json')
        assert response.status_code == 400

    def test_chat_rejects_empty_message(self, logged_in_client):
        """POST /chat avec un message vide doit retourner 400."""
        response = logged_in_client.post('/chat',
            json={'message': '   '},
            content_type='application/json')
        assert response.status_code == 400

    def test_chat_rejects_long_message(self, logged_in_client):
        """POST /chat avec un message trop long doit retourner 400."""
        response = logged_in_client.post('/chat',
            json={'message': 'a' * 2001},
            content_type='application/json')
        assert response.status_code == 400

    @patch('app.get_gemini_response')
    @patch('app.conversations_collection')
    def test_chat_success(self, mock_conv, mock_gemini, logged_in_client):
        """POST /chat avec un message valide doit retourner 200."""
        mock_gemini.return_value = "Réponse du bot"
        mock_conv.find_one.return_value = None
        mock_result = MagicMock()
        mock_result.inserted_id = ObjectId()
        mock_conv.insert_one.return_value = mock_result

        response = logged_in_client.post('/chat',
            json={'message': 'Bonjour'},
            content_type='application/json')
        assert response.status_code == 200
        data = response.get_json()
        assert 'message' in data

    def test_new_chat(self, logged_in_client):
        """POST /new_chat doit retourner 200."""
        response = logged_in_client.post('/new_chat')
        assert response.status_code == 200


class TestAdminRoutes:
    """Tests pour les routes admin."""

    def test_admin_requires_login(self, client):
        """La page admin doit rediriger vers login si non connecté."""
        response = client.get('/admin', follow_redirects=False)
        assert response.status_code == 302

    @patch('app.users_collection')
    def test_admin_requires_admin_role(self, mock_users, logged_in_client):
        """La page admin doit refuser l'accès aux non-admins."""
        mock_users.find_one.return_value = {
            '_id': ObjectId('507f1f77bcf86cd799439011'),
            'username': 'testuser',
            'is_admin': False
        }
        response = logged_in_client.get('/admin', follow_redirects=False)
        assert response.status_code == 302


class TestHistoryAPI:
    """Tests pour l'API de l'historique."""

    @patch('app.conversations_collection')
    def test_get_history(self, mock_conv, logged_in_client):
        """GET /get_history doit retourner l'historique paginé."""
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.skip.return_value = mock_cursor
        mock_cursor.limit.return_value = []
        mock_conv.find.return_value = mock_cursor
        mock_conv.count_documents.return_value = 0

        response = logged_in_client.get('/get_history?page=1')
        assert response.status_code == 200
        data = response.get_json()
        assert 'history' in data
        assert 'page' in data
        assert 'total_pages' in data

    @patch('app.conversations_collection')
    def test_get_chat_invalid_id(self, mock_conv, logged_in_client):
        """GET /get_chat avec un ID invalide doit retourner 400."""
        response = logged_in_client.get('/get_chat/invalid-id')
        assert response.status_code == 400

    @patch('app.conversations_collection')
    def test_get_chat_not_found(self, mock_conv, logged_in_client):
        """GET /get_chat avec un ID inexistant doit retourner 404."""
        mock_conv.find_one.return_value = None
        response = logged_in_client.get('/get_chat/507f1f77bcf86cd799439011')
        assert response.status_code == 404


class TestExportAPI:
    """Tests pour l'export des conversations."""

    def test_export_requires_login(self, client):
        """L'export doit rediriger vers login si non connecté."""
        response = client.get('/export_chat/507f1f77bcf86cd799439011', follow_redirects=False)
        assert response.status_code == 302

    @patch('app.conversations_collection')
    def test_export_txt(self, mock_conv, logged_in_client):
        """L'export TXT doit retourner un fichier texte."""
        mock_conv.find_one.return_value = {
            '_id': ObjectId('507f1f77bcf86cd799439011'),
            'title': 'Test conversation',
            'date': datetime.now(),
            'user_id': '507f1f77bcf86cd799439011',
            'messages': [
                {'user': 'testuser', 'text': 'Bonjour', 'timestamp': datetime.now()},
                {'user': 'Bot', 'text': 'Bonjour !', 'timestamp': datetime.now()}
            ]
        }

        response = logged_in_client.get('/export_chat/507f1f77bcf86cd799439011?format=txt')
        assert response.status_code == 200
        assert 'text/plain' in response.content_type

    @patch('app.conversations_collection')
    def test_export_invalid_id(self, mock_conv, logged_in_client):
        """L'export avec un ID invalide doit rediriger."""
        response = logged_in_client.get('/export_chat/invalid-id', follow_redirects=False)
        assert response.status_code == 302
