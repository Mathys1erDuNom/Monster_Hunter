# economie_db.py
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL, sslmode="require")
cur = conn.cursor()

# Création de la table argent
cur.execute("""
CREATE TABLE IF NOT EXISTS economie (
    user_id TEXT PRIMARY KEY,
    argent INTEGER NOT NULL DEFAULT 0
);
""")
conn.commit()


def _ensure_player(user_id):
    """Crée l'entrée si elle n'existe pas encore."""
    cur.execute("""
        INSERT INTO economie (user_id, argent)
        VALUES (%s, 0)
        ON CONFLICT (user_id) DO NOTHING
    """, (str(user_id),))
    conn.commit()


def get_argent(user_id):
    """Retourne l'argent actuel du joueur (0 si inexistant)."""
    user_id = str(user_id)
    cur.execute("SELECT argent FROM economie WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    if row is None:
        _ensure_player(user_id)
        return 0
    return row[0]


def add_argent(user_id, montant):
    """Ajoute (ou retire si négatif) de l'argent au joueur."""
    user_id = str(user_id)
    _ensure_player(user_id)
    cur.execute("""
        UPDATE economie SET argent = argent + %s
        WHERE user_id = %s
        RETURNING argent
    """, (montant, user_id))
    conn.commit()
    return cur.fetchone()[0]


def has_enough(user_id, montant):
    """Vérifie si le joueur a assez d'argent."""
    return get_argent(user_id) >= montant


def remove_argent(user_id, montant):
    """
    Retire de l'argent si le joueur en a assez.
    Retourne True si la transaction a réussi, False sinon.
    """
    user_id = str(user_id)
    _ensure_player(user_id)
    if not has_enough(user_id, montant):
        return False
    cur.execute("""
        UPDATE economie SET argent = argent - %s
        WHERE user_id = %s
    """, (montant, user_id))
    conn.commit()
    return True


def set_argent(user_id, montant):
    """Fixe l'argent du joueur à une valeur précise."""
    user_id = str(user_id)
    _ensure_player(user_id)
    cur.execute("""
        UPDATE economie SET argent = %s
        WHERE user_id = %s
    """, (montant, user_id))
    conn.commit()
