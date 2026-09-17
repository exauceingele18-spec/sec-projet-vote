import csv
import hashlib
import io
import itertools
import re
import time
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, field_validator

from crypto import CryptoVotingSystem

app = FastAPI(
    title="Système de Vote de Promotion - Bureau CP/CPA/Secrétaire",
    description="Élection académique avec détection antifraude, anonymat des votes et administration dédiée."
)

voting_system = CryptoVotingSystem()

# ------------------------------------------------------------------
# Sécurité admin (à changer avant tout déploiement réel)
# ------------------------------------------------------------------
ADMIN_TOKEN = "GROUPE28-ADMIN-2026"

def require_admin(x_admin_token: Optional[str] = Header(None)):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Accès administrateur refusé. Jeton invalide.")

# ------------------------------------------------------------------
# Validation stricte du matricule : MAT + 5 chiffres, MAJUSCULES obligatoires
# ------------------------------------------------------------------
MATRICULE_PATTERN = re.compile(r"^MAT\d{5}$")

def validate_matricule(raw: str) -> str:
    cleaned = raw.strip()
    if not MATRICULE_PATTERN.fullmatch(cleaned):
        raise HTTPException(
            status_code=400,
            detail="Matricule invalide. Format exigé : MAT suivi de 5 chiffres, en MAJUSCULES (ex : MAT12345)."
        )
    return cleaned

# ------------------------------------------------------------------
# Limite anti-brute-force globale (par adresse IP), indépendante du
# blocage par matricule déjà en place plus bas
# ------------------------------------------------------------------
RATE_LIMIT_WINDOW = 60   # secondes
RATE_LIMIT_MAX = 20      # requêtes de vérification autorisées par fenêtre
_rate_buckets: dict[str, list[float]] = {}

def enforce_rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    bucket = _rate_buckets.setdefault(ip, [])
    bucket[:] = [t for t in bucket if now - t < RATE_LIMIT_WINDOW]
    if len(bucket) >= RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail="Trop de tentatives depuis cette machine. Veuillez patienter une minute avant de réessayer."
        )
    bucket.append(now)

# ------------------------------------------------------------------
# Données en mémoire
# ------------------------------------------------------------------
DEFAULT_PHOTO = "https://images.unsplash.com/photo-1633332755192-727a05c4013d?w=150"

CANDIDATES_BY_ROLE: dict[str, list[dict]] = {
    "CP": [],
    "CPA": [],
    "SECRETAIRE": []
}
_candidate_id_seq = itertools.count(1000)

ROLE_LABELS = {
    "CP": "Chef de Promotion",
    "CPA": "Chef de Promotion Adjoint",
    "SECRETAIRE": "Secrétaire de Promotion"
}

VOTES_DB: list[dict] = []            # anonyme : matricule_hash, role, receipt_hash, timestamp (jamais le candidat + le matricule en clair ensemble)
RECEIPTS_DB: set[str] = set()
VOTERS_REGISTERED: set[str] = set()  # matricules en clair, nécessaire uniquement pour empêcher le double-vote
FAILED_ATTEMPTS: dict[str, int] = {}
AUTHORIZED_VOTERS: set[str] = set()  # registre des matricules autorisés à voter (étudiants en règle avec leurs frais académiques), chargé par l'administrateur
FRAUD_LOG: list[dict] = []           # journal de fraude : matricule, tentative, horodatage
PUBLIC_COMMENTS: list[dict] = []

VOTING_CONFIG = {
    "open_time": None,          # ISO 8601, ex: 2026-09-20T08:00:00+01:00
    "close_time": None,
    "results_published": False
}

# ------------------------------------------------------------------
# Utilitaires
# ------------------------------------------------------------------
def is_voting_open() -> tuple[bool, str]:
    open_t = VOTING_CONFIG["open_time"]
    close_t = VOTING_CONFIG["close_time"]
    if not open_t or not close_t:
        return False, "La période de vote n'a pas encore été configurée par l'administrateur."

    now = datetime.now()
    open_dt = datetime.fromisoformat(open_t)
    close_dt = datetime.fromisoformat(close_t)
    if open_dt.tzinfo is None:
        open_dt = open_dt.replace(tzinfo=None)
    if close_dt.tzinfo is None:
        close_dt = close_dt.replace(tzinfo=None)

    if now < open_dt:
        return False, f"Le vote ouvre le {open_dt.strftime('%d/%m/%Y à %H/%M')}."
    if now > close_dt:
        return False, "La période de vote est terminée."
    return True, ""


def build_results_summary() -> dict:
    total_voters = len(VOTERS_REGISTERED)
    summary_by_role = {}
    for role, cands in CANDIDATES_BY_ROLE.items():
        role_votes = sum(c["votes"] for c in cands)
        role_results = []
        for c in cands:
            percentage = round((c["votes"] / role_votes * 100), 2) if role_votes > 0 else 0.0
            role_results.append({
                "id": c["id"],
                "name": c["name"],
                "photo": c["photo"],
                "votes": c["votes"],
                "percentage": percentage
            })
        role_results.sort(key=lambda r: r["votes"], reverse=True)
        summary_by_role[role] = {
            "label": ROLE_LABELS.get(role, role),
            "total_role_votes": role_votes,
            "candidates": role_results
        }
    return {"total_voters": total_voters, "roles_summary": summary_by_role}


# ------------------------------------------------------------------
# Routes publiques (pages)
# ------------------------------------------------------------------
@app.get("/")
def read_index():
    return FileResponse("index.html")


@app.get("/admin")
def read_admin():
    return FileResponse("admin.html")


# ------------------------------------------------------------------
# API publique - votant
# ------------------------------------------------------------------
@app.get("/api/candidates")
def get_candidates():
    return CANDIDATES_BY_ROLE


@app.get("/api/voting-status")
def voting_status():
    open_ok, msg = is_voting_open()
    return {
        "open": open_ok,
        "message": msg,
        "open_time": VOTING_CONFIG["open_time"],
        "close_time": VOTING_CONFIG["close_time"]
    }


class CheckVoterRequest(BaseModel):
    voter_id: str


@app.post("/api/check-voter")
def check_voter(data: CheckVoterRequest, request: Request):
    enforce_rate_limit(request)

    open_ok, msg = is_voting_open()
    if not open_ok:
        raise HTTPException(status_code=403, detail=msg)

    matricule = validate_matricule(data.voter_id)

    if matricule not in AUTHORIZED_VOTERS:
        raise HTTPException(
            status_code=403,
            detail="Ce matricule ne figure pas dans le registre des électeurs autorisés (étudiants en règle avec leurs frais académiques). Adressez-vous au bureau électoral."
        )

    if matricule in VOTERS_REGISTERED:
        FAILED_ATTEMPTS[matricule] = FAILED_ATTEMPTS.get(matricule, 0) + 1
        attempts = FAILED_ATTEMPTS[matricule]
        FRAUD_LOG.append({
            "matricule": matricule,
            "tentative": attempts,
            "horodatage": datetime.now(timezone.utc).isoformat()
        })
        return {
            "allowed": False,
            "attempts": attempts,
            "message": "Ce matricule a déjà voté !"
        }

    return {"allowed": True, "attempts": 0}


class SingleChoice(BaseModel):
    role: str
    candidate_id: int
    comment: Optional[str] = None


class BallotRequest(BaseModel):
    voter_id: str
    choices: List[SingleChoice]


@app.post("/api/vote")
def cast_ballot(ballot: BallotRequest):
    open_ok, msg = is_voting_open()
    if not open_ok:
        raise HTTPException(status_code=403, detail=msg)

    matricule = validate_matricule(ballot.voter_id)

    if matricule not in AUTHORIZED_VOTERS:
        raise HTTPException(status_code=403, detail="Ce matricule ne figure pas dans le registre des électeurs autorisés.")

    if matricule in VOTERS_REGISTERED:
        raise HTTPException(status_code=400, detail="Accès refusé. Ce matricule a déjà voté.")

    # Le matricule n'est JAMAIS conservé en clair avec le contenu du vote : seul un hachage l'accompagne.
    matricule_hash = hashlib.sha256(matricule.encode()).hexdigest()
    issued_receipts = []

    for item in ballot.choices:
        role = item.role
        candidate_id = item.candidate_id
        cand_found = next((c for c in CANDIDATES_BY_ROLE.get(role, []) if c["id"] == candidate_id), None)

        if cand_found:
            ciphertext, receipt = voting_system.encrypt_vote(candidate_id)
            cand_found["votes"] += 1
            VOTES_DB.append({
                "matricule_hash": matricule_hash,
                "role": role,
                "ciphertext": ciphertext,
                "receipt_hash": receipt,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            RECEIPTS_DB.add(receipt)
            issued_receipts.append({"role": role, "receipt_hash": receipt})

            if item.comment and item.comment.strip():
                PUBLIC_COMMENTS.append({
                    "role": role,
                    "candidate_name": cand_found["name"],
                    "comment": item.comment.strip()
                })

    VOTERS_REGISTERED.add(matricule)
    FAILED_ATTEMPTS.pop(matricule, None)

    return {"status": "Succès", "message": "Votes enregistrés avec succès.", "receipts": issued_receipts}


@app.get("/api/comments")
def get_comments():
    return PUBLIC_COMMENTS


@app.get("/api/results")
def public_results():
    if not VOTING_CONFIG["results_published"]:
        raise HTTPException(status_code=403, detail="Les résultats n'ont pas encore été publiés par l'administration.")
    return build_results_summary()


# ------------------------------------------------------------------
# API administrateur (protégée par X-Admin-Token)
# ------------------------------------------------------------------
@app.get("/api/admin/dashboard")
def admin_dashboard(x_admin_token: Optional[str] = Header(None)):
    require_admin(x_admin_token)
    return build_results_summary()


class CandidateCreate(BaseModel):
    role: str
    name: str
    photo: Optional[str] = None

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v):
        if v not in CANDIDATES_BY_ROLE:
            raise ValueError("Poste invalide.")
        return v


MAX_PHOTO_LENGTH = 2_000_000  # caractères, marge pour une photo encodée en base64 (~1,4 Mo)

@app.post("/api/admin/candidates")
def admin_add_candidate(data: CandidateCreate, x_admin_token: Optional[str] = Header(None)):
    require_admin(x_admin_token)
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Le nom du candidat est requis.")
    photo_value = data.photo.strip() if data.photo else ""
    if len(photo_value) > MAX_PHOTO_LENGTH:
        raise HTTPException(status_code=400, detail="Photo trop volumineuse.")
    candidate = {
        "id": next(_candidate_id_seq),
        "name": name,
        "photo": photo_value or DEFAULT_PHOTO,
        "votes": 0
    }
    CANDIDATES_BY_ROLE[data.role].append(candidate)
    return candidate


class CandidateUpdate(BaseModel):
    name: Optional[str] = None
    photo: Optional[str] = None


@app.put("/api/admin/candidates/{role}/{candidate_id}")
def admin_update_candidate(role: str, candidate_id: int, data: CandidateUpdate, x_admin_token: Optional[str] = Header(None)):
    require_admin(x_admin_token)
    if role not in CANDIDATES_BY_ROLE:
        raise HTTPException(status_code=404, detail="Poste inconnu.")
    cand = next((c for c in CANDIDATES_BY_ROLE[role] if c["id"] == candidate_id), None)
    if not cand:
        raise HTTPException(status_code=404, detail="Candidat introuvable.")
    if data.name and data.name.strip():
        cand["name"] = data.name.strip()
    if data.photo and data.photo.strip():
        cand["photo"] = data.photo.strip()
    return cand


@app.delete("/api/admin/candidates/{role}/{candidate_id}")
def admin_delete_candidate(role: str, candidate_id: int, x_admin_token: Optional[str] = Header(None)):
    require_admin(x_admin_token)
    if role not in CANDIDATES_BY_ROLE:
        raise HTTPException(status_code=404, detail="Poste inconnu.")
    before = len(CANDIDATES_BY_ROLE[role])
    CANDIDATES_BY_ROLE[role] = [c for c in CANDIDATES_BY_ROLE[role] if c["id"] != candidate_id]
    if len(CANDIDATES_BY_ROLE[role]) == before:
        raise HTTPException(status_code=404, detail="Candidat introuvable.")
    return {"status": "Supprimé"}


@app.get("/api/admin/fraud-log")
def admin_fraud_log(x_admin_token: Optional[str] = Header(None)):
    require_admin(x_admin_token)
    return list(reversed(FRAUD_LOG))


@app.get("/api/admin/fraud-log/export")
def admin_export_fraud_log(x_admin_token: Optional[str] = Header(None)):
    require_admin(x_admin_token)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["matricule", "tentative", "horodatage"])
    for entry in FRAUD_LOG:
        writer.writerow([entry["matricule"], entry["tentative"], entry["horodatage"]])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=journal_fraude.csv"}
    )


class AuthorizedVotersImport(BaseModel):
    matricules: str  # texte libre : un matricule par ligne (ou séparés par virgule/espace)


@app.get("/api/admin/authorized-voters")
def admin_list_authorized_voters(x_admin_token: Optional[str] = Header(None)):
    require_admin(x_admin_token)
    return {
        "count": len(AUTHORIZED_VOTERS),
        "matricules": sorted(AUTHORIZED_VOTERS)
    }


@app.post("/api/admin/authorized-voters")
def admin_import_authorized_voters(data: AuthorizedVotersImport, x_admin_token: Optional[str] = Header(None)):
    require_admin(x_admin_token)
    raw_tokens = re.split(r"[\s,;]+", data.matricules.strip())
    added, rejected = [], []
    for token in raw_tokens:
        if not token:
            continue
        if MATRICULE_PATTERN.fullmatch(token):
            AUTHORIZED_VOTERS.add(token)
            added.append(token)
        else:
            rejected.append(token)
    return {"added": len(added), "rejected": rejected, "count": len(AUTHORIZED_VOTERS)}


@app.delete("/api/admin/authorized-voters/{matricule}")
def admin_remove_authorized_voter(matricule: str, x_admin_token: Optional[str] = Header(None)):
    require_admin(x_admin_token)
    AUTHORIZED_VOTERS.discard(matricule.strip())
    return {"count": len(AUTHORIZED_VOTERS)}


@app.get("/api/admin/receipts")
def admin_receipts(x_admin_token: Optional[str] = Header(None)):
    require_admin(x_admin_token)
    # Anonyme : matricule haché uniquement, jamais le matricule en clair ni le candidat choisi.
    return [
        {
            "matricule_hash": v["matricule_hash"],
            "role": v["role"],
            "receipt_hash": v["receipt_hash"],
            "timestamp": v["timestamp"]
        }
        for v in reversed(VOTES_DB)
    ]


@app.get("/api/admin/receipts/export")
def admin_export_receipts(x_admin_token: Optional[str] = Header(None)):
    require_admin(x_admin_token)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["matricule_hash", "role", "receipt_hash", "timestamp"])
    for v in VOTES_DB:
        writer.writerow([v["matricule_hash"], v["role"], v["receipt_hash"], v["timestamp"]])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=recus_vote.csv"}
    )


class ScheduleUpdate(BaseModel):
    open_time: str
    close_time: str


@app.get("/api/admin/schedule")
def admin_get_schedule(x_admin_token: Optional[str] = Header(None)):
    require_admin(x_admin_token)
    return VOTING_CONFIG


@app.post("/api/admin/schedule")
def admin_set_schedule(data: ScheduleUpdate, x_admin_token: Optional[str] = Header(None)):
    require_admin(x_admin_token)
    try:
        open_dt = datetime.fromisoformat(data.open_time)
        close_dt = datetime.fromisoformat(data.close_time)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format de date/heure invalide (ISO 8601 attendu).")
    if close_dt <= open_dt:
        raise HTTPException(status_code=400, detail="L'heure de fermeture doit être postérieure à l'heure d'ouverture.")
    VOTING_CONFIG["open_time"] = data.open_time
    VOTING_CONFIG["close_time"] = data.close_time
    return VOTING_CONFIG


class PublishUpdate(BaseModel):
    published: bool


@app.post("/api/admin/publish-results")
def admin_publish_results(data: PublishUpdate, x_admin_token: Optional[str] = Header(None)):
    require_admin(x_admin_token)
    VOTING_CONFIG["results_published"] = data.published
    return VOTING_CONFIG
