# Plateforme de Vote Électronique Sécurisé — Groupe 28

Projet académique 
Cours *Protocoles de Sécurité Réseau* (M1 MSI, UNIKIN)
Sujet : Développement d'une plateforme web de vote electronique garanstissant confidentialité, intégrité et vérifiabilité.

Pour ce cas nous avons opter de pencher sur l'élection du Bureau de Promotion (Chef de Promotion,
Chef de Promotion Adjoint, Secrétaire de Promotion), avec chiffrement homomorphe
des votes (cryptosystème de Paillier) et anonymisation des matricules (SHA-256).

## Équipe
- INGELE DWAMA Exaucé
- LOBOTA SAMBI Akim
- KONGAWI DAGWA Jacques

## Structure du dépôt
```
.
├── main.py            # API backend (FastAPI)
├── crypto.py           # Module de chiffrement Paillier
├── index.html           # Interface votant
├── admin.html           # Interface administrateur
├── requirements.txt      # Dépendances Python
└── README.md
```


```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

## Liens de déploiement (Render)
- Interface votant : https://sec-projet-vote-api.onrender.com/
- Interface administrateur :https://sec-projet-vote-api.onrender.com/admin


## Fonctionnalités principales
- Authentification par matricule (format strict `MAT` + 5 chiffres, majuscules)
- Registre des électeurs autorisés (géré par l'administrateur)
- Chiffrement homomorphe des bulletins (Paillier) — aucune lecture individuelle possible
- Anonymisation du matricule (hachage SHA-256) avant tout stockage lié à un vote
- Détection et journalisation des tentatives de fraude (double vote)
- Gestion des horaires d'ouverture/fermeture du scrutin
- Publication contrôlée des résultats
- Export CSV du journal de fraude et des reçus (admin)

## Architecture & Base de données

Backend : FastAPI (Python 3)

ORM : SQLAlchemy

Database : PostgreSQL (hébergé sur Render) pour la persistance permanente des données

Sécurité réseau : HTTPS activé automatiquement par Render

## Configuration & Déploiement

Les variables d'environnement suivantes sont utilisées en production :

DATABASE_URL : Chaîne de connexion à la base de données PostgreSQL

ADMIN_TOKEN : Jeton d'authentification pour l'interface administrateur



