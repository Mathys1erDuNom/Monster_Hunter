# inventory_db.py
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL, sslmode="require")
cur = conn.cursor()

# Création de la table inventaire
cur.execute("""
CREATE TABLE IF NOT EXISTS inventory (
    user_id TEXT,
    item_name TEXT,
    quantity INTEGER,
    rarity TEXT,
    description TEXT,
    image TEXT,
    extra TEXT,
    price INTEGER
);
""")
conn.commit()


def add_item(user_id, name, quantity=1, rarity="commun", description="", image="", extra=None, price=0):
    """Ajoute un item à l'inventaire ou augmente sa quantité."""
    user_id = str(user_id)

    cur.execute("""
        SELECT quantity FROM inventory
        WHERE user_id = %s AND item_name = %s
    """, (user_id, name))
    row = cur.fetchone()

    if row:  # Mise à jour
        new_qty = row[0] + quantity
        cur.execute("""
            UPDATE inventory SET quantity = %s
            WHERE user_id = %s AND item_name = %s
        """, (new_qty, user_id, name))
    else:  # Insertion
        cur.execute("""
            INSERT INTO inventory (user_id, item_name, quantity, rarity, description, image, extra, price)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            user_id,
            name,
            quantity,
            rarity,
            description,
            image,
            str(extra) if extra is not None else None,
            price,
        ))

    conn.commit()


def get_inventory(user_id):
    """Retourne tout l'inventaire du joueur."""
    cur.execute("""
        SELECT item_name, quantity, rarity, description, image, extra, price
        FROM inventory
        WHERE user_id = %s
        ORDER BY item_name ASC
    """, (str(user_id),))

    rows = cur.fetchall()
    items = []

    for row in rows:
        items.append({
            "name": row[0],
            "quantity": row[1],
            "rarity": row[2],
            "description": row[3],
            "image": row[4],
            "extra": row[5],
            "price": row[6],
        })

    return items


def delete_inventory(user_id):
    """Supprime tous les items d'un utilisateur."""
    cur.execute("""
        DELETE FROM inventory
        WHERE user_id = %s
    """, (str(user_id),))
    conn.commit()


def use_item(user_id, item_name, quantity=1):
    """
    Décrémente la quantité d'un item et le supprime si nécessaire.
    Retourne la nouvelle quantité et l'extra, ou (None, None) si l'item n'existe pas.
    """
    user_id = str(user_id)
    cur.execute("""
        UPDATE inventory
        SET quantity = quantity - %s
        WHERE user_id = %s AND item_name = %s
        RETURNING quantity, extra
    """, (quantity, user_id, item_name))

    row = cur.fetchone()
    if row is None:
        return None, None

    new_qty, extra = row

    if new_qty <= 0:
        cur.execute("""
            DELETE FROM inventory
            WHERE user_id = %s AND item_name = %s
        """, (user_id, item_name))

    conn.commit()
    return max(new_qty, 0), extra


def get_items(user_id, item_name):
    """Retourne un item spécifique de l'inventaire du joueur, ou None s'il n'existe pas."""
    cur.execute("""
        SELECT item_name, quantity, rarity, description, image, extra, price
        FROM inventory
        WHERE user_id = %s AND item_name = %s
    """, (str(user_id), item_name))
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "name": row[0],
        "quantity": row[1],
        "rarity": row[2],
        "description": row[3],
        "image": row[4],
        "extra": row[5],
        "price": row[6],
    }
