# equipement_db.py
import os
import json
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL, sslmode="require")
cur = conn.cursor()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Chargement des catalogues statiques (armes / armures)
with open(os.path.join(BASE_DIR, "armes.json"), encoding="utf-8") as f:
    ARMES = {a["id"]: a for a in json.load(f)}

with open(os.path.join(BASE_DIR, "armures.json"), encoding="utf-8") as f:
    ARMURES = {a["id"]: a for a in json.load(f)}

# Table qui stocke uniquement l'arme et l'armure ACTUELLEMENT équipées.
# Le fait de "posséder" une arme/armure est géré dans l'inventaire (inventory_db.py),
# item_name = id de l'arme/armure, extra = "arme" ou "armure".
cur.execute("""
CREATE TABLE IF NOT EXISTS equipement (
    user_id TEXT PRIMARY KEY,
    weapon_id TEXT,
    armor_id TEXT
);
""")
conn.commit()


def get_arme(weapon_id):
    return ARMES.get(weapon_id)


def get_armure(armor_id):
    return ARMURES.get(armor_id)


def _ensure_player(user_id):
    cur.execute("""
        INSERT INTO equipement (user_id, weapon_id, armor_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id) DO NOTHING
    """, (str(user_id), "epee_bois", "tunique_tissu"))
    conn.commit()


def get_equipement(user_id):
    """Retourne l'id de l'arme et de l'armure équipées (arme/armure de base par défaut)."""
    user_id = str(user_id)
    cur.execute("SELECT weapon_id, armor_id FROM equipement WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    if row is None:
        _ensure_player(user_id)
        return {"weapon_id": "epee_bois", "armor_id": "tunique_tissu"}
    return {"weapon_id": row[0], "armor_id": row[1]}


def equiper_arme(user_id, weapon_id):
    """Équipe une arme (doit être possédée dans l'inventaire, à vérifier côté appelant)."""
    if weapon_id not in ARMES:
        return False
    user_id = str(user_id)
    _ensure_player(user_id)
    cur.execute("UPDATE equipement SET weapon_id = %s WHERE user_id = %s", (weapon_id, user_id))
    conn.commit()
    return True


def equiper_armure(user_id, armor_id):
    """Équipe une armure (doit être possédée dans l'inventaire, à vérifier côté appelant)."""
    if armor_id not in ARMURES:
        return False
    user_id = str(user_id)
    _ensure_player(user_id)
    cur.execute("UPDATE equipement SET armor_id = %s WHERE user_id = %s", (armor_id, user_id))
    conn.commit()
    return True


def get_bonus_combat(user_id):
    """
    Retourne les bonus de combat apportés par l'équipement porté :
    degat_arme, element_arme, defense_armure, element_armure
    """
    eq = get_equipement(user_id)
    arme = get_arme(eq["weapon_id"]) or get_arme("epee_bois")
    armure = get_armure(eq["armor_id"]) or get_armure("tunique_tissu")

    return {
        "degat_arme": arme["degat"],
        "element_arme": arme["element"],
        "defense_armure": armure["defense"],
        "element_armure": armure["element"],
    }
