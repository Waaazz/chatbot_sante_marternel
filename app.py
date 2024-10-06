from flask import Flask, request, jsonify, render_template
from pymongo import MongoClient
from config import Config
import spacy
from twilio.rest import Client
from datetime import datetime
import os
from config import Config

# Initialiser l'application Flask
app = Flask(__name__)
app.config.from_object(Config)

# Connexion à MongoDB
client = MongoClient(app.config['MONGO_URI'])
db = client['chatbot']
users_collection = db['users']
appointments_collection= db['Rappel']

# Charger le modèle de SpaCy pour le français
nlp = spacy.load('fr_core_news_sm')

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
    data = request.json
    phone_number = data.get('phone_number')

    if not phone_number:
        return jsonify({"error": "Numéro de téléphone requis"}), 400

    existing_user = users_collection.find_one({'phone_number': phone_number})

    if existing_user:
        return jsonify({"message": "Utilisateur déjà enregistré"}), 200

    new_user = {
        "phone_number": phone_number,
        "consultations": [],
        "reminders": []
    }
    users_collection.insert_one(new_user)
    
    return jsonify({"message": "Utilisateur enregistré avec succès"}), 201

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
        if ent.label_ == "PER":
            user_data['name'] = ent.text
        if ent.label_ == "AGE":
            user_data['age'] = ent.text
        if "semaines" in user_message:
            user_data['weeks_pregnant'] = int([t for t in doc if t.is_digit][0].text)
    
    return user_data


# API pour interagir avec le chatbot
@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json['message']
    user_data = extract_user_data(user_message)  # Extraction des données utilisateur (nom, âge, grossesse)
    
    response_message = handle_user_message(user_data, user_message)
    
    return jsonify({"message": response_message})

# Fonction pour gérer les messages utilisateur
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
    # Réponses pour la grossesse
    if "symptômes" in message:
        return "Les symptômes courants incluent les nausées matinales, la fatigue, et des maux de tête. Consultez un médecin si vous avez des symptômes sévères."
    if "alimentation" in message:
        return "Assurez-vous de consommer des aliments riches en nutriments comme des légumes, des fruits, des protéines maigres et des céréales complètes."
    if "exercices" in message:
        return "Des exercices légers comme la marche, le yoga prénatal, ou la natation sont recommandés pendant la grossesse."
    if "signes de danger" in message:
        return "Les signes de danger incluent des douleurs abdominales sévères, des saignements ou une diminution des mouvements du bébé. Consultez immédiatement votre médecin."
    
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



# Route pour afficher la page de Conseiller médical
@app.route('/contact_advisor', methods=['GET'])
def show_contact_advisor_form():
    return render_template('contact_advisor.html')


# Lancer l'application
if __name__ == "__main__":
    app.run(debug=True)