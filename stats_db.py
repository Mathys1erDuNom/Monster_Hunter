# stats_db.py
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL, sslmode="require")
cur = conn.cursor()

# Stats de base à la création d'un personnage
HP_BASE = 100
ATTAQUE_BASE = 10
DEFENSE_BASE = 5
XP_NIVEAU_BASE = 100  # xp nécessaire pour passer du niveau 1 au niveau 2

# Création de la table stats
cur.execute("""
CREATE TABLE IF NOT EXISTS player_stats (
    user_id TEXT PRIMARY KEY,
    hp INTEGER NOT NULL,
    hp_max INTEGER NOT NULL,
    attaque INTEGER NOT NULL,
    defense INTEGER NOT NULL,
    current_xp INTEGER NOT NULL DEFAULT 0,
    xp_niveau INTEGER NOT NULL DEFAULT 100,
    niveau INTEGER NOT NULL DEFAULT 1,
    points_dispo INTEGER NOT NULL DEFAULT 0
);
""")
conn.commit()


def xp_requis_pour(niveau):
    """Formule de progression de l'xp requis (croissance simple)."""
    return int(XP_NIVEAU_BASE * (1.25 ** (niveau - 1)))


def player_exists(user_id):
    cur.execute("SELECT 1 FROM player_stats WHERE user_id = %s", (str(user_id),))
    return cur.fetchone() is not None


def create_player(user_id):
    """Crée un joueur avec ses stats de base si il n'existe pas déjà."""
    user_id = str(user_id)
    if player_exists(user_id):
        return get_stats(user_id)

    cur.execute("""
        INSERT INTO player_stats (user_id, hp, hp_max, attaque, defense, current_xp, xp_niveau, niveau, points_dispo)
        VALUES (%s, %s, %s, %s, %s, 0, %s, 1, 0)
    """, (user_id, HP_BASE, HP_BASE, ATTAQUE_BASE, DEFENSE_BASE, xp_requis_pour(1)))
    conn.commit()
    return get_stats(user_id)


def get_stats(user_id):
    """Retourne les stats du joueur (le crée si besoin)."""
    user_id = str(user_id)
    cur.execute("""
        SELECT hp, hp_max, attaque, defense, current_xp, xp_niveau, niveau, points_dispo
        FROM player_stats WHERE user_id = %s
    """, (user_id,))
    row = cur.fetchone()
    if row is None:
        return create_player(user_id)

    return {
        "hp": row[0],
        "hp_max": row[1],
        "attaque": row[2],
        "defense": row[3],
        "current_xp": row[4],
        "xp_niveau": row[5],
        "niveau": row[6],
        "points_dispo": row[7],
    }


def is_dead(user_id):
    return get_stats(user_id)["hp"] <= 0


def heal(user_id, montant):
    """Soigne le joueur, sans dépasser son hp_max. Retourne le nouveau hp."""
    user_id = str(user_id)
    stats = get_stats(user_id)
    nouveau_hp = min(stats["hp"] + montant, stats["hp_max"])
    cur.execute("UPDATE player_stats SET hp = %s WHERE user_id = %s", (nouveau_hp, user_id))
    conn.commit()
    return nouveau_hp


def full_heal(user_id):
    """Soigne complètement le joueur (utilisé après un combat / respawn)."""
    user_id = str(user_id)
    stats = get_stats(user_id)
    cur.execute("UPDATE player_stats SET hp = %s WHERE user_id = %s", (stats["hp_max"], user_id))
    conn.commit()
    return stats["hp_max"]


def damage(user_id, montant):
    """
    Inflige des dégâts au joueur. Ne descend pas sous 0.
    Retourne (nouveau_hp, est_mort).
    """
    user_id = str(user_id)
    stats = get_stats(user_id)
    nouveau_hp = max(stats["hp"] - montant, 0)
    cur.execute("UPDATE player_stats SET hp = %s WHERE user_id = %s", (nouveau_hp, user_id))
    conn.commit()
    return nouveau_hp, nouveau_hp <= 0


def add_xp(user_id, xp_gagne):
    """
    Ajoute de l'xp au joueur, gère la montée de niveau (potentiellement
    plusieurs niveaux d'un coup). Retourne un dict avec les infos de
    progression : {niveau_avant, niveau_apres, leveled_up, points_dispo}.
    """
    user_id = str(user_id)
    stats = get_stats(user_id)
    niveau_avant = stats["niveau"]

    current_xp = stats["current_xp"] + xp_gagne
    niveau = stats["niveau"]
    xp_niveau = stats["xp_niveau"]
    points_dispo = stats["points_dispo"]

    leveled_up = False
    while current_xp >= xp_niveau:
        current_xp -= xp_niveau
        niveau += 1
        xp_niveau = xp_requis_pour(niveau)
        points_dispo += 2  # 2 points de stats à répartir par niveau gagné
        leveled_up = True

    cur.execute("""
        UPDATE player_stats
        SET current_xp = %s, xp_niveau = %s, niveau = %s, points_dispo = %s
        WHERE user_id = %s
    """, (current_xp, xp_niveau, niveau, points_dispo, user_id))
    conn.commit()

    return {
        "niveau_avant": niveau_avant,
        "niveau_apres": niveau,
        "leveled_up": leveled_up,
        "points_dispo": points_dispo,
    }


STAT_MAP = {
    "hp": "hp_max",
    "attaque": "attaque",
    "defense": "defense",
}


def allouer_point(user_id, stat_name, valeur=5):
    """
    Utilise un point de stat disponible pour augmenter une stat.
    stat_name doit être 'hp', 'attaque' ou 'defense'.
    Retourne False s'il n'y a pas de point disponible ou si le nom est invalide.
    """
    user_id = str(user_id)
    if stat_name not in STAT_MAP:
        return False

    stats = get_stats(user_id)
    if stats["points_dispo"] <= 0:
        return False

    colonne = STAT_MAP[stat_name]
    if colonne == "hp_max":
        # augmenter le hp max augmente aussi le hp courant du même montant
        cur.execute("""
            UPDATE player_stats
            SET hp_max = hp_max + %s, hp = hp + %s, points_dispo = points_dispo - 1
            WHERE user_id = %s
        """, (valeur, valeur, user_id))
    else:
        cur.execute(f"""
            UPDATE player_stats
            SET {colonne} = {colonne} + %s, points_dispo = points_dispo - 1
            WHERE user_id = %s
        """, (valeur, user_id))

    conn.commit()
    return True
