# Plateforme de Vote Électronique Sécurisé — Groupe 28

Projet académique — Cours *Protocoles de Sécurité Réseau* (M1 MSI, UNIKIN)
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

## Installation et exécution en local

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Puis ouvrir :
- Interface votant : http://127.0.0.1:8000/
- Interface administrateur : http://127.0.0.1:8000/admin

## Fonctionnalités principales
- Authentification par matricule (format strict `MAT` + 5 chiffres, majuscules)
- Registre des électeurs autorisés (géré par l'administrateur)
- Chiffrement homomorphe des bulletins (Paillier) — aucune lecture individuelle possible
- Anonymisation du matricule (hachage SHA-256) avant tout stockage lié à un vote
- Détection et journalisation des tentatives de fraude (double vote)
- Gestion des horaires d'ouverture/fermeture du scrutin
- Publication contrôlée des résultats
- Export CSV du journal de fraude et des reçus (admin)

## Sécurité — points à changer avant tout déploiement réel
- Le jeton administrateur (`ADMIN_TOKEN` dans `main.py`) est une constante en clair :
  à remplacer par une variable d'environnement.
- Les données sont conservées en mémoire vive (perdues au redémarrage) : à brancher
  sur une base de données persistante pour un usage réel.
- Aucun HTTPS n'est configuré ici : à activer en production.

## Documentation
Le rapport complet du projet et la présentation associée figurent dans ce dépôt
(ou ont été transmis séparément selon les consignes du cours).
