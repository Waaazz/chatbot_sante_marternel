from flask import Flask, request, jsonify
from pymongo import MongoClient
from config import Config
import spacy
from twilio.rest import Client  # Importer Twilio pour envoyer des SMS

# Initialiser l'application Flask
app = Flask(__name__)
app.config.from_object(Config)

# Connexion à MongoDB
client = MongoClient(app.config['MONGO_URI'])
db = client['chatbot']  # Base de données 'chatbot'
users_collection = db['users']  # Collection 'users' pour stocker les utilisateurs

# Charger le modèle de SpaCy pour l'anglais
nlp = spacy.load('en_core_web_sm')

# Route simple pour tester que l'application fonctionne
@app.route('/')
def home():
    return "Chatbot de santé maternelle et infantile fonctionne!"

# Route pour l'enregistrement des utilisateurs avec gestion des requêtes GET et POST
@app.route('/register', methods=['GET', 'POST'])
def register_user():
    if request.method == 'GET':
        return "Utilisez une requête POST pour enregistrer un utilisateur."

    # Traitement de la requête POST
    data = request.json
    phone_number = data.get('phone_number')
    
    if not phone_number:
        return jsonify({"error": "Numéro de téléphone requis"}), 400
    
    # Vérifier si l'utilisateur existe déjà
    existing_user = users_collection.find_one({'phone_number': phone_number})
    
    if existing_user:
        return jsonify({"message": "Utilisateur déjà enregistré", "user": existing_user}), 200
    
    # Créer un nouvel utilisateur
    new_user = {
        "phone_number": phone_number,
        "consultations": [],
        "reminders": []
    }
    users_collection.insert_one(new_user)
    
    return jsonify({"message": "Utilisateur enregistré avec succès"}), 201

# Route pour traiter les questions des utilisateurs via SpaCy
@app.route('/ask', methods=['POST'])
def ask_question():
    data = request.json
    question = data.get('question')

    if not question:
        return jsonify({"error": "Question requise"}), 400

    # Analyse de la question avec SpaCy
    doc = nlp(question)
    tokens = [token.text for token in doc]

    # Réponse en fonction des mots-clés
    if "grossesse" in tokens or "enceinte" in tokens:
        response = "Pour des informations sur la grossesse, veuillez consulter un professionnel de santé."
    elif "vaccin" in tokens:
        response = "N'oubliez pas de vacciner votre enfant selon le calendrier."
    else:
        response = "Je suis désolé, je ne comprends pas encore cette question."

    return jsonify({"response": response})

# Fonction pour envoyer des SMS via Twilio
def send_sms(to, body):
    client = Client(app.config['TWILIO_ACCOUNT_SID'], app.config['TWILIO_AUTH_TOKEN'])

    # Créer et envoyer le message
    message = client.messages.create(
        body=body,
        from_=app.config['TWILIO_PHONE_NUMBER'],
        to=to
    )
    
    return message.sid

# Route pour envoyer un rappel par SMS
@app.route('/reminder', methods=['POST'])
def send_reminder():
    data = request.json
    phone_number = data.get('phone_number')
    reminder_message = data.get('message')
    
    if not phone_number or not reminder_message:
        return jsonify({"error": "Numéro de téléphone et message requis"}), 400

    # Envoyer le message via Twilio
    try:
        message_sid = send_sms(phone_number, reminder_message)
        return jsonify({"message": "Rappel envoyé", "sid": message_sid}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Démarrer l'application Flask
if __name__ == "__main__":
    app.run(debug=True)
