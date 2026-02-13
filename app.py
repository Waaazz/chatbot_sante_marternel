from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, session
from pymongo import MongoClient
from config import Config
import spacy
from twilio.rest import Client
from datetime import datetime
import os
import re
import logging
from bson import ObjectId
from bson.errors import InvalidId
from flask_mail import Mail, Message
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from google import genai
from google.genai import types
import io

load_dotenv()

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Initialiser l'application Flask
app = Flask(__name__)
app.config.from_object(Config)

# Initialisation de Flask-Mail
mail = Mail(app)

# Initialisation du rate limiter
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Connexion à MongoDB
client = MongoClient(app.config['MONGO_URI'])
db = client['chatbot']
users_collection = db['users']
reminders_collection = db['reminders']
conversations_collection = db['conversations']

# Initialisation du serializer avec la clé secrète
ts = URLSafeTimedSerializer(app.config["SECRET_KEY"])

# Charger le modèle de SpaCy pour le français
nlp = spacy.load('fr_core_news_sm')

# Configuration de Google Gemini (nouveau SDK google-genai)
gemini_client = None
GEMINI_MODEL = 'gemini-2.5-flash-lite'
GEMINI_SYSTEM_PROMPT = """Tu es un assistant spécialisé en santé maternelle et infantile, particulièrement au Burkina Faso.
Tu donnes des conseils sur : la grossesse, les soins prénatals et postnataux, l'allaitement, la nutrition des enfants, les vaccinations, les signes de danger pendant la grossesse.
Tu réponds toujours en français, de manière bienveillante et accessible.
Tu ne donnes jamais de diagnostic médical. Tu orientes vers un professionnel de santé si la situation semble grave.
Tu gardes tes réponses concises (2-4 paragraphes maximum).
Si la question n'est pas liée à la santé maternelle ou infantile, tu le signales poliment et proposes de répondre sur ces sujets."""

if app.config.get('GEMINI_API_KEY'):
    try:
        gemini_client = genai.Client(api_key=app.config['GEMINI_API_KEY'])
        logger.info("Google Gemini configuré avec succès (SDK google-genai)")
    except Exception as e:
        logger.warning("Impossible de configurer Gemini : %s", e)
else:
    logger.info("GEMINI_API_KEY non configurée, utilisation du mode fallback")

# Regex de validation
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
PHONE_REGEX = re.compile(r'^\+?\d{8,15}$')


# En-têtes de sécurité sur toutes les réponses
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response


# Pages d'erreur personnalisées
@app.errorhandler(404)
def page_not_found(e):
    return render_template('errors/404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    logger.error("Erreur serveur 500 : %s", e)
    return render_template('errors/500.html'), 500


@app.errorhandler(429)
def too_many_requests(e):
    return render_template('errors/429.html'), 429


# Décorateur pour protéger les routes qui nécessitent une connexion
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Veuillez vous connecter pour accéder à cette page', 'error')
            return redirect(url_for('show_login_form'))
        return f(*args, **kwargs)
    return decorated_function


# Décorateur pour les routes admin
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Veuillez vous connecter', 'error')
            return redirect(url_for('show_login_form'))
        user = users_collection.find_one({"_id": ObjectId(session['user_id'])})
        if not user or not user.get('is_admin', False):
            flash('Accès réservé aux administrateurs', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function


# Route simple pour afficher la page d'accueil
@app.route('/')
def home():
    return render_template('index.html')


# Route pour afficher la page d'inscription
@app.route('/register', methods=['GET'])
def show_register_form():
    return render_template('register.html')


# Route pour l'enregistrement des utilisateurs
@app.route('/register', methods=['POST'])
@limiter.limit("3 per minute")
def register_user():
    data = request.form
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')
    confirm_password = data.get('confirm_password', '')

    if not username or not email or not password or not confirm_password:
        flash('Tous les champs sont requis', 'error')
        return redirect(url_for('show_register_form'))

    # Validation du format email
    if not EMAIL_REGEX.match(email):
        flash('Format d\'email invalide', 'error')
        return redirect(url_for('show_register_form'))

    # Validation de la longueur du mot de passe
    if len(password) < 8:
        flash('Le mot de passe doit contenir au moins 8 caractères', 'error')
        return redirect(url_for('show_register_form'))

    if password != confirm_password:
        flash('Les mots de passe ne correspondent pas', 'error')
        return redirect(url_for('show_register_form'))

    existing_user = users_collection.find_one({'email': email})

    if existing_user:
        flash('Cet email est déjà enregistré', 'error')
        return redirect(url_for('show_register_form'))

    # Générer un token de confirmation
    token = ts.dumps(email, salt='email-confirm-key')

    # Enregistrer l'utilisateur avec mot de passe haché
    new_user = {
        "username": username,
        "email": email,
        "password": generate_password_hash(password),
        "confirmed": False,
        "confirmation_token": token,
        "registration_date": datetime.now()
    }
    users_collection.insert_one(new_user)
    logger.info("Nouvel utilisateur inscrit : %s", username)

    # Envoyer l'email de confirmation
    confirmation_link = url_for('confirm_email', token=token, _external=True)
    try:
        send_confirmation_email(username, email, confirmation_link)
        flash('Un email de confirmation a été envoyé à votre adresse. Veuillez le vérifier.', 'success')
    except Exception:
        logger.warning("Échec de l'envoi de l'email de confirmation pour %s", email)
        flash('Le compte a été créé mais l\'email de confirmation n\'a pas pu être envoyé. Veuillez réessayer ou contacter le support.', 'error')
    return redirect(url_for('registration_success', username=username))


# Route pour la page de confirmation de l'inscription
@app.route('/registration_success/<username>', methods=['GET'])
def registration_success(username):
    return render_template('registration_success.html', user={'username': username})


# Route pour confirmer l'email
@app.route('/confirm/<token>', methods=['GET'])
def confirm_email(token):
    try:
        email = ts.loads(token, salt='email-confirm-key', max_age=86400)  # 24 heures
    except (SignatureExpired, BadSignature):
        flash('Le lien de confirmation est invalide ou a expiré', 'error')
        return redirect(url_for('show_register_form'))

    user = users_collection.find_one({'email': email})

    if user and not user['confirmed']:
        users_collection.update_one({'_id': user['_id']}, {'$set': {'confirmed': True}})
        flash('Votre compte a été activé avec succès. Vous pouvez maintenant vous connecter.', 'success')
    else:
        flash('Votre compte est déjà activé. Vous pouvez vous connecter.', 'success')
    return redirect(url_for('show_login_form'))


# Route pour afficher la page de connexion
@app.route('/login', methods=['GET'])
def show_login_form():
    return render_template('login.html')


# Route pour traiter le formulaire de connexion
@app.route('/login', methods=['POST'])
@limiter.limit("5 per minute")
def login():
    data = request.form
    username = data.get('username', '').strip()
    password = data.get('password', '')

    user = users_collection.find_one({'username': username, 'confirmed': True})

    if user and check_password_hash(user['password'], password):
        session['user_id'] = str(user['_id'])
        session['username'] = user['username']
        session.permanent = True
        logger.info("Connexion réussie : %s", username)
        flash('Connexion réussie', 'success')
        return redirect(url_for('home'))
    else:
        logger.warning("Tentative de connexion échouée pour : %s", username)
        flash('Nom d\'utilisateur ou mot de passe incorrect', 'error')
        return redirect(url_for('show_login_form'))


# Route pour la déconnexion
@app.route('/logout')
def logout():
    username = session.get('username', 'inconnu')
    session.clear()
    logger.info("Déconnexion : %s", username)
    flash('Vous avez été déconnecté', 'success')
    return redirect(url_for('home'))


# Route pour afficher le formulaire de mot de passe oublié
@app.route('/forgot_password', methods=['GET'])
def show_forgot_password():
    return render_template('forgot_password.html')


# Route pour traiter la demande de réinitialisation
@app.route('/forgot_password', methods=['POST'])
@limiter.limit("3 per minute")
def forgot_password():
    email = request.form.get('email', '').strip()

    if not email or not EMAIL_REGEX.match(email):
        flash('Veuillez entrer une adresse email valide', 'error')
        return redirect(url_for('show_forgot_password'))

    user = users_collection.find_one({'email': email, 'confirmed': True})

    # Message générique pour ne pas révéler si l'email existe
    if user:
        token = ts.dumps(email, salt='password-reset-key')
        reset_link = url_for('reset_password', token=token, _external=True)
        try:
            send_reset_email(user['username'], email, reset_link)
        except Exception:
            logger.warning("Échec de l'envoi de l'email de réinitialisation pour %s", email)

    flash('Si un compte existe avec cet email, un lien de réinitialisation a été envoyé.', 'success')
    return redirect(url_for('show_forgot_password'))


# Route pour afficher/traiter le formulaire de nouveau mot de passe
@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = ts.loads(token, salt='password-reset-key', max_age=3600)  # 1 heure
    except (SignatureExpired, BadSignature):
        flash('Le lien de réinitialisation est invalide ou a expiré', 'error')
        return redirect(url_for('show_forgot_password'))

    if request.method == 'GET':
        return render_template('reset_password.html', token=token)

    password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password', '')

    if len(password) < 8:
        flash('Le mot de passe doit contenir au moins 8 caractères', 'error')
        return render_template('reset_password.html', token=token)

    if password != confirm_password:
        flash('Les mots de passe ne correspondent pas', 'error')
        return render_template('reset_password.html', token=token)

    users_collection.update_one(
        {'email': email},
        {'$set': {'password': generate_password_hash(password)}}
    )
    logger.info("Mot de passe réinitialisé pour : %s", email)
    flash('Votre mot de passe a été réinitialisé avec succès. Vous pouvez vous connecter.', 'success')
    return redirect(url_for('show_login_form'))


# Fonction pour envoyer l'email de confirmation
def send_confirmation_email(username, email, confirmation_link):
    msg = Message('Activation de votre compte', sender=app.config['MAIL_DEFAULT_SENDER'], recipients=[email])
    msg.body = f"""Bonjour {username},

Veuillez cliquer sur le lien ci-dessous pour activer votre compte :

{confirmation_link}

Cordialement,
L'équipe de votre site."""
    mail.send(msg)


# Fonction pour envoyer l'email de réinitialisation
def send_reset_email(username, email, reset_link):
    msg = Message('Réinitialisation de votre mot de passe', sender=app.config['MAIL_DEFAULT_SENDER'], recipients=[email])
    msg.body = f"""Bonjour {username},

Vous avez demandé la réinitialisation de votre mot de passe.
Cliquez sur le lien ci-dessous (valide 1 heure) :

{reset_link}

Si vous n'avez pas fait cette demande, ignorez cet email.

Cordialement,
L'équipe de votre site."""
    mail.send(msg)


# Route pour afficher la page de questions
@app.route('/ask', methods=['GET'])
@login_required
def show_ask_form():
    return render_template('chatbot.html')


# Fonction pour extraire les données utilisateur
def extract_user_data(user_message):
    """Extraire les informations utilisateur (nom, âge, grossesse) à partir du message."""
    doc = nlp(user_message)
    user_data = {}

    for ent in doc.ents:
        if ent.label_ == "PER":
            user_data['name'] = ent.text
        elif ent.label_ == "DATE":
            if "semaine" in ent.text.lower():
                nums = [t for t in ent if t.like_num]
                if nums:
                    try:
                        user_data['weeks_pregnant'] = int(nums[0].text)
                    except ValueError:
                        pass

    # Extraction par regex en fallback
    if 'weeks_pregnant' not in user_data:
        match = re.search(r'(\d+)\s*semaine', user_message.lower())
        if match:
            user_data['weeks_pregnant'] = int(match.group(1))

    return user_data


# Générer une réponse avec Gemini (nouveau SDK google-genai)
def get_gemini_response(user_message, conversation_history):
    """Appelle l'API Gemini avec le contexte de conversation."""
    if not gemini_client:
        return None

    try:
        # Construire l'historique pour Gemini (format nouveau SDK)
        history = []
        for msg in conversation_history[-10:]:  # Max 10 derniers messages
            role = "user" if msg.get("user") != "Bot" else "model"
            history.append(types.Content(
                role=role,
                parts=[types.Part.from_text(text=msg.get("text", ""))]
            ))

        chat = gemini_client.chats.create(
            model=GEMINI_MODEL,
            config=types.GenerateContentConfig(
                system_instruction=GEMINI_SYSTEM_PROMPT
            ),
            history=history
        )
        response = chat.send_message(user_message)
        return response.text
    except Exception as e:
        logger.warning("Erreur Gemini : %s", e)
        return None


# Route pour démarrer une nouvelle conversation
@app.route('/new_chat', methods=['POST'])
@login_required
def new_chat():
    session.pop('conversation_id', None)
    return jsonify({"message": "Nouvelle conversation démarrée"})


# API pour interagir avec le chatbot
@app.route('/chat', methods=['POST'])
@login_required
@limiter.limit("30 per minute")
def chat():
    data = request.json
    if not data or 'message' not in data:
        return jsonify({"error": "Message requis"}), 400

    user_message = data['message']

    # Validation de la longueur du message
    if not isinstance(user_message, str) or len(user_message) > 2000:
        return jsonify({"error": "Le message ne doit pas dépasser 2000 caractères"}), 400

    user_message = user_message.strip()
    if not user_message:
        return jsonify({"error": "Message requis"}), 400

    now = datetime.now()
    conversation_id = session.get('conversation_id')
    conversation_history = []

    # Récupérer la conversation existante si elle existe
    if conversation_id:
        try:
            existing = conversations_collection.find_one({"_id": ObjectId(conversation_id)})
            if existing and existing.get("user_id") == session.get('user_id'):
                conversation_history = existing.get("messages", [])
        except Exception:
            session.pop('conversation_id', None)

    # Générer la réponse : Gemini en priorité, fallback local
    response_message = get_gemini_response(user_message, conversation_history)
    if not response_message:
        user_data = extract_user_data(user_message)
        response_message = handle_user_message(user_data, user_message)

    # Construire les documents de messages
    user_msg = {
        "user": session.get('username', 'Inconnu'),
        "text": user_message,
        "timestamp": now
    }
    bot_msg = {
        "user": "Bot",
        "text": response_message,
        "timestamp": now
    }

    if conversation_id:
        # Ajouter les messages à la conversation existante
        conversations_collection.update_one(
            {"_id": ObjectId(conversation_id)},
            {"$push": {"messages": {"$each": [user_msg, bot_msg]}},
             "$set": {"date": now}}
        )
    else:
        # Créer une nouvelle conversation
        chat_title = generate_chat_title([], user_message)
        result = conversations_collection.insert_one({
            "title": chat_title,
            "date": now,
            "user_id": session.get('user_id'),
            "messages": [user_msg, bot_msg]
        })
        session['conversation_id'] = str(result.inserted_id)

    return jsonify({"message": response_message})


def handle_user_message(user_data, message):
    """Gérer les différentes requêtes de l'utilisateur en fonction du contexte."""
    message_lower = message.lower()

    pregnancy_keywords = [
        "symptômes", "alimentation", "exercices",
        "signes de danger", "soins prénatals", "soins postnataux",
        "visites médicales", "nutriments", "yoga prénatal",
        "visites prénatales", "tests de dépistage", "préparations pour l'accouchement",
        "soins du nouveau-né", "allaitement", "alimentation du bébé", "reprise après l'accouchement",
        "nutrition des enfants", "aliments solides", "alimentation équilibrée"
    ]
    personalized_suggestions_keywords = [
        "trimestre", "âge de l'enfant", "âge", "nouveau-né", "bébé", "enfant"
    ]

    if any(keyword in message_lower for keyword in pregnancy_keywords):
        return pregnancy_info(user_data, message_lower)

    if any(keyword in message_lower for keyword in personalized_suggestions_keywords):
        return personalized_suggestions(user_data, message_lower)

    return "Je ne suis pas sûr de comprendre. Pouvez-vous reformuler? Vous pouvez me poser des questions sur : les symptômes, l'alimentation, les exercices, les soins prénatals, les soins postnataux, les vaccinations, la nutrition des enfants, etc."


def pregnancy_info(user_data, message):
    """Fournir des informations sur la grossesse, les soins prénatals et postnataux, et la nutrition des enfants."""
    name = user_data.get('name', 'utilisatrice')
    weeks_pregnant = user_data.get('weeks_pregnant', None)

    if "symptômes" in message:
        if weeks_pregnant:
            return f"Bonjour {name}, à {weeks_pregnant} semaines de grossesse, les symptômes courants incluent les nausées, la fatigue, les maux de tête, et les douleurs dans le bas du dos. Consultez un médecin si vous ressentez des douleurs sévères, des saignements ou une diminution des mouvements du bébé."
        return "Les symptômes courants de la grossesse incluent les nausées, la fatigue, les maux de tête et les douleurs dans le bas du dos. Consultez un médecin si vous ressentez des douleurs sévères ou des saignements."

    if "alimentation équilibrée" in message:
        return "Une alimentation équilibrée pour les enfants doit inclure des légumes, fruits, protéines maigres, produits laitiers et céréales complètes."

    if "alimentation du bébé" in message:
        return "L'allaitement est recommandé pendant les premiers mois. Si vous ne pouvez pas allaiter, parlez-en à votre médecin pour choisir un lait infantile adapté."

    if "alimentation" in message:
        return "Pendant la grossesse, il est essentiel d'avoir une alimentation équilibrée. Consommez des fruits, légumes, protéines maigres, céréales complètes, et produits laitiers. Limitez les aliments trop gras ou trop sucrés et évitez l'alcool et le tabac."

    if "exercices" in message:
        return "Des exercices légers comme la marche, le yoga prénatal, et la natation sont recommandés. Évitez les sports intenses ou les activités à risque. Consultez votre médecin avant de commencer un programme d'exercices."

    if "tests de dépistage" in message:
        return "Les tests de dépistage prénatals incluent les échographies, les tests de dépistage de la trisomie et des anomalies génétiques."

    if "préparations pour l'accouchement" in message:
        return "Il est conseillé de suivre des cours de préparation à l'accouchement, de préparer une valise pour l'hôpital, et de discuter d'un plan de naissance avec votre médecin."

    if "soins prénatals" in message or "visites prénatales" in message:
        return "Il est recommandé de planifier une visite prénatale toutes les 4 semaines pendant les premiers mois de grossesse, puis tous les 15 jours à partir du 7ème mois. Ces visites incluent des échographies, des tests de dépistage, et des bilans sanguins."

    if "soins postnataux" in message:
        return "Après l'accouchement, surveillez votre santé et celle de votre bébé. Consultez votre médecin pour des conseils sur l'allaitement et la reprise de vos activités."

    if "soins du nouveau-né" in message:
        return "Les soins du nouveau-né incluent la surveillance du poids, l'allaitement, le nettoyage du cordon ombilical et la vaccination."

    if "allaitement" in message:
        return "L'allaitement est recommandé pendant les premiers mois. Si vous ne pouvez pas allaiter, parlez-en à votre médecin pour choisir un lait infantile adapté."

    if "reprise après l'accouchement" in message:
        return "La reprise après l'accouchement peut inclure des exercices doux, mais il est important d'attendre l'approbation de votre médecin avant de reprendre des activités intenses."

    if "nutrition des enfants" in message:
        return "Une bonne nutrition est essentielle pour le développement des enfants. Assurez-vous de leur donner des repas équilibrés, riches en légumes, fruits, et protéines."

    if "aliments solides" in message:
        return "L'introduction des aliments solides commence généralement à 6 mois. Commencez par des purées de légumes, fruits et céréales pour bébés."

    if "signes de danger" in message:
        return "Les signes de danger pendant la grossesse incluent : saignements vaginaux, maux de tête sévères, vision floue, douleurs abdominales intenses, fièvre élevée, et diminution des mouvements du bébé. Consultez immédiatement un médecin."

    return "Je peux vous fournir des informations sur la grossesse, les soins prénatals, postnataux, ou la nutrition des enfants. De quoi avez-vous besoin ?"


def personalized_suggestions(user_data, message):
    """Fournir des suggestions en fonction de la durée de la grossesse ou de l'âge de l'enfant."""
    weeks_pregnant = user_data.get('weeks_pregnant', 0)
    if "trimestre" in message:
        if weeks_pregnant <= 12:
            return "Premier trimestre : Il est recommandé de suivre une alimentation riche en acide folique et de planifier votre première visite prénatale."
        if 13 <= weeks_pregnant <= 26:
            return "Deuxième trimestre : Continuez à suivre vos visites prénatales. Vous pouvez commencer à préparer l'arrivée du bébé."
        if weeks_pregnant >= 27:
            return "Troisième trimestre : Assurez-vous que tout est prêt pour l'accouchement. Faites des exercices doux et suivez les conseils de votre médecin."
    if "nouveau-né" in message:
        return "Pour un nouveau-né, il est important de suivre des horaires réguliers d'allaitement ou de biberon et de surveiller son sommeil."
    if "bébé" in message:
        return "Pour un bébé de 6 mois, vous pouvez commencer à introduire des aliments solides en petites quantités, tout en continuant l'allaitement."
    if "enfant" in message:
        return "Assurez-vous que votre enfant mange équilibré, avec des fruits, des légumes, et des protéines. Encouragez également l'activité physique quotidienne."
    return "Je peux vous fournir des conseils basés sur la durée de votre grossesse ou l'âge de votre enfant."


# Route pour afficher la page de Rappel
@app.route('/add_reminder', methods=['GET'])
@login_required
def show_add_reminder_form():
    return render_template('add_reminder.html')


def save_appointment(user_data, appointment_date, reminder_date, reminder_time):
    """Enregistrer un rappel de rendez-vous ou vaccination dans MongoDB."""
    reminders_collection.insert_one({
        "name": user_data.get("name"),
        "phone_number": user_data.get("phone_number"),
        "appointment_date": appointment_date,
        "reminder_date": reminder_date,
        "reminder_time": reminder_time,
        "type": "rappel"
    })


@app.route('/set_reminder', methods=['POST'])
@login_required
@limiter.limit("5 per minute")
def set_reminder():
    data = request.json
    name = data.get('name', '').strip() if data.get('name') else ''
    reminder_type = data.get('type', '').strip() if data.get('type') else ''
    reminder_date = data.get('date', '').strip() if data.get('date') else ''
    reminder_time = data.get('time', '').strip() if data.get('time') else ''
    phone_number = data.get('phone', '').strip() if data.get('phone') else ''

    if not all([name, reminder_type, reminder_date, phone_number]):
        return jsonify({'message': 'Erreur: Veuillez remplir tous les champs.'}), 400

    # Validation du numéro de téléphone
    phone_clean = phone_number.replace(' ', '').replace('-', '')
    if not PHONE_REGEX.match(phone_clean):
        return jsonify({'message': 'Erreur: Format de numéro de téléphone invalide.'}), 400

    save_appointment({
        'name': name,
        'phone_number': phone_number,
    }, reminder_date, reminder_date, reminder_time)

    message = f"Bonjour {name}, votre rappel de {reminder_type} est fixé pour le {reminder_date} à {reminder_time}."
    sms_sent = send_sms(phone_number, message)

    if sms_sent:
        return jsonify({'message': 'Rappel enregistré et SMS envoyé avec succès!'})
    return jsonify({'message': 'Rappel enregistré, mais le SMS n\'a pas pu être envoyé. Vérifiez le numéro de téléphone.'})


def send_sms(to, message):
    """Envoyer un SMS via Twilio. Retourne True si envoyé, False sinon."""
    account_sid = Config.TWILIO_ACCOUNT_SID
    auth_token = Config.TWILIO_AUTH_TOKEN
    twilio_number = Config.TWILIO_PHONE_NUMBER

    try:
        twilio_client = Client(account_sid, auth_token)
        twilio_client.messages.create(
            body=message,
            from_=twilio_number,
            to=to
        )
        return True
    except Exception as e:
        logger.error("Erreur d'envoi SMS : %s", e)
        return False


# Route pour la page de contact conseiller
@app.route('/contact', methods=['GET'])
@login_required
def show_contact_form():
    return render_template('contact_advisor.html')


# Route pour contacter un conseiller médical
@app.route('/contact_advisor', methods=['POST'])
@login_required
@limiter.limit("3 per minute")
def contact_advisor():
    data = request.json
    phone_number = data.get('phone_number', '').strip() if data.get('phone_number') else ''
    name = data.get('name', '').strip() if data.get('name') else ''
    email = data.get('email', '').strip() if data.get('email') else ''
    message = data.get('message', '').strip() if data.get('message') else ''

    if not all([phone_number, name, email, message]):
        return jsonify({"error": "Numéro de téléphone, nom, email et message requis"}), 400

    # Validation du format email
    if not EMAIL_REGEX.match(email):
        return jsonify({"error": "Format d'email invalide"}), 400

    # Validation du numéro de téléphone
    phone_clean = phone_number.replace(' ', '').replace('-', '')
    if not PHONE_REGEX.match(phone_clean):
        return jsonify({"error": "Format de numéro de téléphone invalide"}), 400

    advisor_phone = app.config.get('ADVISOR_PHONE_NUMBER')
    sms_sent = send_sms(advisor_phone, f"Message de {name} ({phone_number}, {email}): {message}")

    if sms_sent:
        return jsonify({"message": "Message envoyé au conseiller avec succès"}), 200
    return jsonify({"message": "Votre message a été enregistré, mais le SMS au conseiller n'a pas pu être envoyé. Il sera contacté par un autre moyen."}), 200


# Route pour récupérer l'historique des messages
@app.route('/get_history', methods=['GET'])
@login_required
def get_history():
    user_id = session.get('user_id')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    per_page = min(per_page, 50)  # Maximum 50 par page

    query = {"user_id": user_id}
    total = conversations_collection.count_documents(query)
    total_pages = max(1, (total + per_page - 1) // per_page)

    history = conversations_collection.find(query).sort("date", -1).skip((page - 1) * per_page).limit(per_page)
    history_list = []
    for chat in history:
        chat_dict = {
            "id": str(chat["_id"]),
            "title": chat.get("title", "Sans titre"),
            "date": chat["date"].strftime('%Y-%m-%d %H:%M:%S'),
            "messages": [
                {
                    "user": msg.get("user", "Inconnu"),
                    "text": msg.get("text", ""),
                    "timestamp": msg.get("timestamp", datetime.now()).strftime('%Y-%m-%d %H:%M:%S')
                }
                for msg in chat.get("messages", [])
            ]
        }
        history_list.append(chat_dict)
    return jsonify({"history": history_list, "page": page, "total_pages": total_pages})


def generate_chat_title(messages, user_message):
    """Génère un titre pour le chat en fonction du message utilisateur."""
    first_message = user_message
    if messages:
        oldest = min(messages, key=lambda m: m.get('timestamp', datetime.now()))
        if oldest.get('text'):
            first_message = oldest['text']

    keywords = re.findall(r'\b\w+\b', first_message)
    title = ' '.join(keywords[:5])
    return title


# Route pour récupérer un chat spécifique
@app.route('/get_chat/<chat_id>', methods=['GET'])
@login_required
def get_chat(chat_id):
    # Validation de l'ObjectId
    try:
        oid = ObjectId(chat_id)
    except (InvalidId, Exception):
        return jsonify({"error": "Identifiant de chat invalide"}), 400

    chat = conversations_collection.find_one({"_id": oid})

    if not chat:
        return jsonify({"error": "Chat non trouvé"}), 404

    # Vérification d'autorisation : le chat doit appartenir à l'utilisateur
    if chat.get("user_id") and chat.get("user_id") != session.get('user_id'):
        return jsonify({"error": "Accès non autorisé"}), 403

    chat_dict = {
        "id": str(chat["_id"]),
        "title": chat.get("title", "Sans titre"),
        "date": chat["date"].strftime('%Y-%m-%d %H:%M:%S'),
        "messages": [
            {
                "user": msg.get("user", "Inconnu"),
                "text": msg.get("text", ""),
                "timestamp": msg.get("timestamp", datetime.now()).strftime('%Y-%m-%d %H:%M:%S')
            }
            for msg in chat.get("messages", [])
        ]
    }
    return jsonify(chat_dict)


# Page de profil utilisateur
@app.route('/profile', methods=['GET'])
@login_required
def show_profile():
    user = users_collection.find_one({"_id": ObjectId(session['user_id'])})
    if not user:
        flash('Utilisateur non trouvé', 'error')
        return redirect(url_for('home'))
    return render_template('profile.html', user=user)


@app.route('/profile', methods=['POST'])
@login_required
@limiter.limit("5 per minute")
def update_profile():
    user = users_collection.find_one({"_id": ObjectId(session['user_id'])})
    if not user:
        flash('Utilisateur non trouvé', 'error')
        return redirect(url_for('home'))

    action = request.form.get('action')

    if action == 'update_info':
        new_username = request.form.get('username', '').strip()
        new_email = request.form.get('email', '').strip()

        if not new_username or not new_email:
            flash('Le nom d\'utilisateur et l\'email sont requis', 'error')
            return redirect(url_for('show_profile'))

        if not EMAIL_REGEX.match(new_email):
            flash('Format d\'email invalide', 'error')
            return redirect(url_for('show_profile'))

        existing = users_collection.find_one({'email': new_email, '_id': {'$ne': user['_id']}})
        if existing:
            flash('Cet email est déjà utilisé par un autre compte', 'error')
            return redirect(url_for('show_profile'))

        existing_name = users_collection.find_one({'username': new_username, '_id': {'$ne': user['_id']}})
        if existing_name:
            flash('Ce nom d\'utilisateur est déjà pris', 'error')
            return redirect(url_for('show_profile'))

        users_collection.update_one(
            {'_id': user['_id']},
            {'$set': {'username': new_username, 'email': new_email}}
        )
        session['username'] = new_username
        flash('Informations mises à jour avec succès', 'success')

    elif action == 'change_password':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not check_password_hash(user['password'], current_password):
            flash('Mot de passe actuel incorrect', 'error')
            return redirect(url_for('show_profile'))

        if len(new_password) < 8:
            flash('Le nouveau mot de passe doit contenir au moins 8 caractères', 'error')
            return redirect(url_for('show_profile'))

        if new_password != confirm_password:
            flash('Les nouveaux mots de passe ne correspondent pas', 'error')
            return redirect(url_for('show_profile'))

        users_collection.update_one(
            {'_id': user['_id']},
            {'$set': {'password': generate_password_hash(new_password)}}
        )
        flash('Mot de passe modifié avec succès', 'success')

    return redirect(url_for('show_profile'))


# Export des conversations
@app.route('/export_chat/<chat_id>')
@login_required
def export_chat(chat_id):
    try:
        oid = ObjectId(chat_id)
    except (InvalidId, Exception):
        flash('Identifiant de chat invalide', 'error')
        return redirect(url_for('show_ask_form'))

    chat = conversations_collection.find_one({"_id": oid})
    if not chat or chat.get("user_id") != session.get('user_id'):
        flash('Conversation non trouvée', 'error')
        return redirect(url_for('show_ask_form'))

    export_format = request.args.get('format', 'txt')

    if export_format == 'pdf':
        return export_chat_pdf(chat)
    return export_chat_txt(chat)


def export_chat_txt(chat):
    """Exporter une conversation en fichier texte."""
    output = io.StringIO()
    title = chat.get('title', 'Conversation')
    date = chat['date'].strftime('%Y-%m-%d %H:%M')
    output.write(f"{'='*50}\n")
    output.write(f"  {title}\n")
    output.write(f"  Date: {date}\n")
    output.write(f"{'='*50}\n\n")

    for msg in chat.get('messages', []):
        user = msg.get('user', 'Inconnu')
        text = msg.get('text', '')
        timestamp = msg.get('timestamp', datetime.now()).strftime('%H:%M')
        output.write(f"[{timestamp}] {user}:\n{text}\n\n")

    content = output.getvalue()
    response = app.response_class(content, mimetype='text/plain; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename="conversation_{chat["_id"]}.txt"'
    return response


def export_chat_pdf(chat):
    """Exporter une conversation en fichier PDF."""
    try:
        from fpdf import FPDF
    except ImportError:
        flash('Export PDF non disponible (fpdf2 non installé)', 'error')
        return redirect(url_for('show_ask_form'))

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    pdf.set_font('Helvetica', 'B', 16)
    title = chat.get('title', 'Conversation')
    safe_title = title.encode('latin-1', 'replace').decode('latin-1')
    pdf.cell(0, 10, safe_title, ln=True, align='C')

    pdf.set_font('Helvetica', '', 10)
    date = chat['date'].strftime('%Y-%m-%d %H:%M')
    pdf.cell(0, 8, f"Date: {date}", ln=True, align='C')
    pdf.ln(10)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)

    for msg in chat.get('messages', []):
        user = msg.get('user', 'Inconnu')
        text = msg.get('text', '')
        timestamp = msg.get('timestamp', datetime.now()).strftime('%H:%M')

        if user == 'Bot':
            pdf.set_font('Helvetica', 'B', 10)
            pdf.set_text_color(0, 150, 199)
        else:
            pdf.set_font('Helvetica', 'B', 10)
            pdf.set_text_color(233, 30, 140)

        safe_user = user.encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(0, 6, f"[{timestamp}] {safe_user}:", ln=True)
        pdf.set_font('Helvetica', '', 9)
        pdf.set_text_color(51, 51, 51)
        safe_text = text.encode('latin-1', 'replace').decode('latin-1')
        pdf.multi_cell(0, 5, safe_text)
        pdf.ln(3)

    pdf_bytes = pdf.output()
    response = app.response_class(pdf_bytes, mimetype='application/pdf')
    response.headers['Content-Disposition'] = f'attachment; filename="conversation_{chat["_id"]}.pdf"'
    return response


# Panel d'administration
@app.route('/admin')
@admin_required
def admin_panel():
    total_users = users_collection.count_documents({})
    total_confirmed = users_collection.count_documents({"confirmed": True})
    total_conversations = conversations_collection.count_documents({})
    total_reminders = reminders_collection.count_documents({})

    recent_users = list(users_collection.find().sort("registration_date", -1).limit(20))
    users_list = []
    for u in recent_users:
        users_list.append({
            "username": u.get("username", ""),
            "email": u.get("email", ""),
            "confirmed": u.get("confirmed", False),
            "registration_date": u.get("registration_date", datetime.now()).strftime('%Y-%m-%d %H:%M'),
            "is_admin": u.get("is_admin", False)
        })

    stats = {
        "total_users": total_users,
        "total_confirmed": total_confirmed,
        "total_conversations": total_conversations,
        "total_reminders": total_reminders
    }
    return render_template('admin.html', stats=stats, users=users_list)


# Lancer l'application
if __name__ == "__main__":
    app.run(debug=app.config.get('DEBUG', False))
