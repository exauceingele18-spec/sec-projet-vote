import hashlib
from phe import paillier

class CryptoVotingSystem:
    def __init__(self):
        # Génération des clés au démarrage (en production, la clé privée est conservée par l'autorité de vote)
        self.public_key, self.private_key = paillier.generate_paillier_keypair(n_length=2048)

    def encrypt_vote(self, vote_choice: int) -> tuple[str, str]:
        """
        Chiffre le choix du vote (ex: 1 ou 0) avec la clé publique Paillier.
        Retourne le texte chiffré (str) et un reçu unique (SHA-256) pour la vérifiabilité.
        """
        encrypted_vote = self.public_key.encrypt(vote_choice)

        # Génération d'un reçu d'audit pour le votant (Vérifiabilité individuelle)
        receipt_hash = hashlib.sha256(f"{encrypted_vote.ciphertext()}".encode()).hexdigest()

        return str(encrypted_vote.ciphertext()), receipt_hash

    def aggregate_and_decrypt(self, encrypted_vote_ciphertexts: list[int]) -> int:
        """
        Additionne homomorphiquement tous les votes chiffrés SANS les déchiffrer un par un,
        puis déchiffre le total final avec la clé privée.
        """
        if not encrypted_vote_ciphertexts:
            return 0

        # Reconstruction des objets EncryptedNumber
        encrypted_numbers = [
            paillier.EncryptedNumber(self.public_key, ciphertext)
            for ciphertext in encrypted_vote_ciphertexts
        ]

        # Addition homomorphe : E(A) + E(B) = E(A + B)
        total_encrypted = sum(encrypted_numbers)

        # Déchiffrement du résultat global uniquement (Confidentialité préservée)
        return self.private_key.decrypt(total_encrypted)
