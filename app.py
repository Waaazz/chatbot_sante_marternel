from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from pymongo import MongoClient
from config import Config
import spacy
from transformers import pipeline
from twilio.rest import Client
from datetime import datetime
import os
from config import Config
from bson import ObjectId
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
from dotenv import load_dotenv

load_dotenv()
# Initialiser l'application Flask
app = Flask(__name__)
app.config.from_object(Config)

# Initialisation de Flask-Mail
mail = Mail(app)

# Connexion à MongoDB
client = MongoClient(app.config['MONGO_URI'])
db = client['chatbot']
users_collection = db['users']
appointments_collection= db['Rappel']
messages_collection = db['messages']
conversations_collection = db['conversations']

# Initialisation du serializer avec la clé secrète
ts = URLSafeTimedSerializer(app.config["SECRET_KEY"])
# Initialisation du serializer pour la validation par email
ts = URLSafeTimedSerializer(app.config["SECRET_KEY"])

# Charger le modèle de SpaCy pour le français
nlp = spacy.load('fr_core_news_sm')
# Charger le modèle de langage pré-entraîné
nlp_model = pipeline("text2text-generation", model="t5-small")

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
def register_user():
    data = request.form
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    confirm_password = data.get('confirm_password')

    if not username or not email or not password or not confirm_password:
        flash('Tous les champs sont requis', 'error')
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

    # Enregistrer l'utilisateur avec le token
    new_user = {
        "username": username,
        "email": email,
        "password": password,
        "confirmed": False,
        "confirmation_token": token,
        "registration_date": datetime.now()
    }
    users_collection.insert_one(new_user)

    # Envoyer l'email de confirmation
    confirmation_link = url_for('confirm_email', token=token, _external=True)
    send_confirmation_email(username, email, confirmation_link)

    flash('Un email de confirmation a été envoyé à votre adresse. Veuillez le vérifier.', 'success')
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
    except:
        flash('Le lien de confirmation est invalide ou a expiré', 'error')
        return redirect(url_for('show_register_form'))

    user = users_collection.find_one({'email': email})

    if user and not user['confirmed']:
        users_collection.update_one({'_id': user['_id']}, {'$set': {'confirmed': True}})
        flash('Votre compte a été activé avec succès. Vous pouvez maintenant vous connecter.', 'success')
        return redirect(url_for('login'))
    else:
        flash('Votre compte est déjà activé. Vous pouvez vous connecter.', 'success')
        return redirect(url_for('login'))

# Route pour afficher la page de connexion
@app.route('/login', methods=['GET'])
def show_login_form():
    return render_template('login.html')

# Route pour traiter le formulaire de connexion
@app.route('/login', methods=['POST'])
def login():
    data = request.form
    username = data.get('username')
    password = data.get('password')

    user = users_collection.find_one({'username': username, 'password': password, 'confirmed': True})

    if user:
        flash('Connexion réussie', 'success')
        return redirect(url_for('home'))
    else:
        flash('Nom d\'utilisateur ou mot de passe incorrect', 'error')
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
# Route pour afficher la page de questions
@app.route('/ask', methods=['GET'])
def show_ask_form():
    return render_template('chatbot.html')

# Fonction pour extraire les données utilisateur
def extract_user_data(user_message):
    """Extraire les informations utilisateur (nom, âge, grossesse) à partir du message."""
    doc = nlp(user_message)
    user_data = {}
    
    for ent in doc.ents:
        if ent.label_ == "PER":  # Entité pour le nom de personne
            user_data['name'] = ent.text
        elif ent.label_ == "AGE":  # Entité pour l'âge
            user_data['age'] = ent.text
        elif ent.label_ == "DATE":  # Entité pour les dates (ex. semaines de grossesse)
            # Extraire les semaines si mentionné dans un contexte de grossesse
            if "semaine" in ent.text.lower():
                user_data['weeks_pregnant'] = int([t for t in ent if t.like_num][0].text)

    return user_data


# API pour interagir avec le chatbot
@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json['message']
    user_data = extract_user_data(user_message)  # Extraction des données utilisateur (nom, âge, grossesse)
    
    response_message = handle_user_message(user_data, user_message)
    
    # Enregistrer le message utilisateur dans MongoDB
    user_message_doc = {
        "user": user_data.get('name', 'Inconnu'),
        "text": user_message,
        "timestamp": datetime.now()
    }
    messages_collection.insert_one(user_message_doc)

    # Enregistrer la réponse du bot
    bot_message_doc = {
        "user": "Bot",
        "text": response_message,
        "timestamp": datetime.now()
    }
    messages_collection.insert_one(bot_message_doc)

    # Récupérer les 10 derniers messages pour générer le titre
    messages = list(messages_collection.find().sort("timestamp", -1).limit(10))
    
    # Générer un titre pour le chat
    chat_title = generate_chat_title(messages, user_message)

    # Enregistrer le chat dans la collection des conversations
    conversations_collection.insert_one({
        "title": chat_title,
        "date": datetime.now(),
        "messages": messages
    })
    return jsonify({"message": response_message})


def handle_user_message(user_data, message):
    """Gérer les différentes requêtes de l'utilisateur en fonction du contexte."""
    # Mots-clés pour les différents sujets liés à la grossesse
    pregnancy_keywords = [
        "symptômes", "alimentation", "exercices", 
        "signes de danger", "soins prénatals", "soins postnataux",  
        "visites médicales" , "nutriments", "yoga prénatal"
        "visites prénatales", "tests de dépistage", "préparations pour l'accouchement",
        "soins du nouveau-né", "allaitement", "alimentation du bébé", "reprise après l'accouchement",
        "nutrition des enfants", "aliments solides", "alimentation équilibrée"
    ]
    # Mots-clés pour les suggestions personnalisées basées sur la grossesse et l'âge de l'enfant
    personalized_suggestions_keywords = [
        "trimestre", "âge de l'enfant", "âge", "nouveau-né", "bébé", "enfant"
    ]
    # Vérifiez si l'un des mots-clés de grossesse est présent dans le message
    if any(keyword in message for keyword in pregnancy_keywords):
        return pregnancy_info(user_data, message)  
     
    # Vérifiez si l'un des mots-clés pour les suggestions personnalisées est présent
    if any(keyword in message for keyword in personalized_suggestions_keywords):
        return personalized_suggestions(user_data, message)
    
    return "Je ne suis pas sûr de comprendre. Pouvez-vous reformuler?"

# Réponses automatiques sur la grossesse, les soins et la nutrition des enfants
def pregnancy_info(user_data, message):
    """Fournir des informations sur la grossesse, les soins prénatals et postnataux, et la nutrition des enfants."""
    name = user_data.get('name', 'utilisatrice')
    weeks_pregnant = user_data.get('weeks_pregnant', None)

    if "symptômes" in message:
        return f"Bonjour {name}, à {weeks_pregnant} semaines de grossesse, les symptômes courants incluent les nausées, la fatigue, les maux de tête, et les douleurs dans le bas du dos. Consultez un médecin si vous ressentez des douleurs sévères, des saignements ou une diminution des mouvements du bébé."

    if "alimentation" in message:
        return "Pendant la grossesse, il est essentiel d'avoir une alimentation équilibrée. Consommez des fruits, légumes, protéines maigres, céréales complètes, et produits laitiers. Limitez les aliments trop gras ou trop sucrés et évitez l'alcool et le tabac."

    if "exercices" in message:
        return "Des exercices légers comme la marche, le yoga prénatal, et la natation sont recommandés. Évitez les sports intenses ou les activités à risque. Consultez votre médecin avant de commencer un programme d'exercices."

    if "soins prénatals" in message:
        return "Il est recommandé de planifier une visite prénatale toutes les 4 semaines pendant les premiers mois de grossesse, puis tous les 15 jours à partir du 7ème mois. Ces visites incluent des échographies, des tests de dépistage, et des bilans sanguins pour surveiller votre santé et celle du bébé."

    if "visites prénatales" in message:
        return "Les visites prénatales sont cruciales pour surveiller le bon déroulement de la grossesse. Pensez à faire vos visites régulièrement pour garantir la santé du bébé et la vôtre."

    if "préparations pour l'accouchement" in message:
        return "Il est conseillé de suivre des cours de préparation à l'accouchement, de préparer une valise pour l'hôpital, et de discuter d'un plan de naissance avec votre médecin."

    # Soins prénatals
    if "soins prénatals" in message:
        return "Il est recommandé de planifier des visites prénatales toutes les 4 semaines. Les tests de dépistage prénatals incluent les échographies et les analyses de sang."
    if "visites prénatales" in message:
        return "Les visites prénatales sont importantes pour surveiller la santé de la mère et du bébé. Elles incluent des examens réguliers de tension artérielle, des échographies et des analyses sanguines."
    if "tests de dépistage" in message:
        return "Les tests de dépistage prénatals incluent les échographies, les tests de dépistage de la trisomie et des anomalies génétiques."
    if "préparations pour l'accouchement" in message:
        return "Il est conseillé de suivre des cours de préparation à l'accouchement, de planifier l'hôpital ou la maternité, et de discuter d'un plan de naissance avec votre médecin."
    
    # Soins postnataux
    if "soins postnataux" in message:
        return "Après l'accouchement, surveillez votre santé et celle de votre bébé. Consultez votre médecin pour des conseils sur l'allaitement et la reprise de vos activités."
    if "soins du nouveau-né" in message:
        return "Les soins du nouveau-né incluent la surveillance du poids, l'allaitement, le nettoyage du cordon ombilical et la vaccination."
    if "allaitement" in message or "alimentation du bébé" in message:
        return "L'allaitement est recommandé pendant les premiers mois. Si vous ne pouvez pas allaiter, parlez-en à votre médecin pour choisir un lait infantile adapté."
    if "reprise après l'accouchement" in message:
        return "La reprise après l'accouchement peut inclure des exercices doux, mais il est important d'attendre l'approbation de votre médecin avant de reprendre des activités intenses."
    
    # Nutrition des enfants
    if "nutrition des enfants" in message:
        return "Une bonne nutrition est essentielle pour le développement des enfants. Assurez-vous de leur donner des repas équilibrés, riches en légumes, fruits, et protéines."
    if "aliments solides" in message:
        return "L'introduction des aliments solides commence généralement à 6 mois. Commencez par des purées de légumes, fruits et céréales pour bébés."
    if "alimentation équilibrée" in message:
        return "Une alimentation équilibrée pour les enfants doit inclure des légumes, fruits, protéines maigres, produits laitiers et céréales complètes."
    
    return "Je peux vous fournir des informations sur la grossesse, les soins prénatals, postnataux, ou la nutrition des enfants. De quoi avez-vous besoin ?"

# Suggestions personnalisées basées sur la grossesse et l'âge de l'enfant
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
    if  "nouveau-né" in message:
        return "Pour un nouveau-né, il est important de suivre des horaires réguliers d'allaitement ou de biberon et de surveiller son sommeil."
    if  "bébé"in message :
        return "Pour un bébé de 6 mois, vous pouvez commencer à introduire des aliments solides en petites quantités, tout en continuant l'allaitement."
    if "enfant" in message:
        return "Assurez-vous que votre enfant mange équilibré, avec des fruits, des légumes, et des protéines. Encouragez également l'activité physique quotidienne."
    return "Je peux vous fournir des conseils basés sur la durée de votre grossesse ou l'âge de votre enfant."
# Ajoutez d'autres fonctions pour gérer les rendez-vous, les rappels, etc.
# Route pour afficher la page de Rappel
@app.route('/add_reminder', methods=['GET'])
def show_add_reminder_form():
    return render_template('add_reminder.html')


def save_appointment(user_data, appointment_date, reminder_date, reminder_time):
    """Enregistrer un rappel de rendez-vous ou vaccination dans MongoDB."""
    
    # Enregistrer dans la collection des rendez-vous (appointments)
    appointments_collection.insert_one({
        "name": user_data.get("name"),  # Nom de l'utilisateur
        "phone_number": user_data.get("phone_number"),  # Numéro de téléphone
        "appointment_date": appointment_date,  # Date du rendez-vous
        "reminder_date": reminder_date,  # Date du rappel (ex: un jour avant)
        "reminder_time": reminder_time,  # Heure de rappel
        "type": "rappel"  # Type de rappel (visite prénatale, postnatale, vaccination)
    })

    print(f"Rappel pour {user_data['name']} enregistré avec succès pour le {appointment_date}.")


@app.route('/set_reminder', methods=['POST'])
def set_reminder():
    data = request.json
    name = data.get('name') 
    reminder_type = data.get('type')
    reminder_date = data.get('date')
    reminder_time = data.get('time')  
    phone_number = data.get('phone')

    if reminder_type and reminder_date and phone_number:
        # Enregistrer le rappel dans MongoDB (ou toute autre action)
        save_appointment({
            'name': name,  # Remplacer par le nom de l'utilisateur si disponible
            'phone_number': phone_number,
        }, reminder_date, reminder_date, reminder_time,)  # Enregistrer le rappel et la date de rappel

        # Préparer le message SMS
        message = f"Bonjour {name}, votre rappel de {reminder_type} est fixé pour le {reminder_date} à {reminder_time}."
        
        # Envoyer le SMS
        send_sms(phone_number, message)
        
        return jsonify({'message': 'Rappel enregistré avec succès!'})
    return jsonify({'message': 'Erreur: Veuillez remplir tous les champs.'}), 400

def send_sms(to, message):
    account_sid = Config.TWILIO_ACCOUNT_SID  # Variable d'environnement
    auth_token = Config.TWILIO_AUTH_TOKEN    # Variable d'environnement
    twilio_number = Config.TWILIO_PHONE_NUMBER     # Variable d'environnement

    client = Client(account_sid, auth_token)
    client.messages.create(
        body=message,
        from_=twilio_number,
        to=to
    )
    print(f"SMS envoyé à {to}: {message}")



# Route pour contacter un conseiller médical
@app.route('/contact_advisor', methods=['POST'])
def contact_advisor():
    data = request.json
    phone_number = data.get('phone_number')
    name = data.get('name')
    email = data.get('email')
    message = data.get('message')

    if not phone_number or not name or not email or not message:
        return jsonify({"error": "Numéro de téléphone, nom, email et message requis"}), 400

    advisor_phone = "+22654125637"  # Numéro fictif d'un conseiller médical
    send_sms(advisor_phone, f"Message de {name} ({phone_number}, {email}): {message}")

    return jsonify({"message": "Message envoyé au conseiller"}), 200

# Route pour récupérer l'historique des messages
@app.route('/get_history', methods=['GET'])
def get_history():
    history = conversations_collection.find().sort("date", -1)  # Tri par ordre chronologique
    history_list = []
    for chat in history:
        # Convertir les ObjectId en chaînes de caractères
        chat_dict = {
            "id": str(chat["_id"]),
            "title": chat["title"],
            "date": chat["date"].strftime('%Y-%m-%d %H:%M:%S'),
            "messages": [
                {
                    "user": message.get("user", "Inconnu"),  # Utiliser "Inconnu" si la clé 'user' n'existe pas
                    "text": message.get("text", ""),  # Utiliser une chaîne vide si la clé 'text' n'existe pas
                    "timestamp": message.get("timestamp", datetime.now()).strftime('%Y-%m-%d %H:%M:%S')  # Utiliser la date actuelle si la clé 'timestamp' n'existe pas
                }
                for message in chat["messages"]
            ]
        }
        history_list.append(chat_dict)
    return jsonify({"history": history_list})

import re
def generate_chat_title(messages, user_message):
    """Génère un titre pour le chat en fonction du premier message."""
    if messages:
        first_message = messages[0]['text']
    else:
        first_message = user_message

    # Utilisez une expression régulière pour extraire les mots clés
    keywords = re.findall(r'\b\w+\b', first_message)
    title = ' '.join(keywords[:5])  # Utilisez les 5 premiers mots comme titre
    return title

# Route pour récupérer un chat spécifique
@app.route('/get_chat/<chat_id>', methods=['GET'])
def get_chat(chat_id):
    chat = conversations_collection.find_one({"_id": ObjectId(chat_id)})
    if chat:
        chat_dict = {
            "id": str(chat["_id"]),
            "title": chat["title"],
            "date": chat["date"].strftime('%Y-%m-%d %H:%M:%S'),
            "messages": [
                {
                    "user": message.get("user", "Inconnu"),  # Utiliser "Inconnu" si la clé 'user' n'existe pas
                    "text": message.get("text", ""),  # Utiliser une chaîne vide si la clé 'text' n'existe pas
                    "timestamp": message.get("timestamp", datetime.now()).strftime('%Y-%m-%d %H:%M:%S')  # Utiliser la date actuelle si la clé 'timestamp' n'existe pa
                }
                for message in chat["messages"]
            ]
        }
        return jsonify(chat_dict)
    else:
        return jsonify({"error": "Chat not found"}), 404

# Lancer l'application
if __name__ == "__main__":
    app.run(debug=True)