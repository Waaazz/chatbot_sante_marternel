# app.py

from flask import Flask, request, jsonify
from pymongo import MongoClient
from config import Config

# Initialiser l'application Flask
app = Flask(__name__)
app.config.from_object(Config)

# Connexion à MongoDB
client = MongoClient(app.config['MONGO_URI'])
db = client['chatbot']  # Base de données 'chatbot'
users_collection = db['users']  # Collection 'users' pour stocker les utilisateurs

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

# Démarrer l'application
if __name__ == "__main__":
    app.run(debug=True)
