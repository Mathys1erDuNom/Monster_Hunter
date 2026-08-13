# Bot Monster Hunter — architecture

## Fichiers

| Fichier | Rôle |
|---|---|
| `bot.py` | Point d'entrée, charge le cog et démarre la boucle de spawn sur chaque serveur (salon `#chasse`) |
| `monster_hunter.py` | Cog principal : commandes `!chasse`, `!attaque`, `!esquive`, `!soin`, `!info_monstre`, `!loot`, `!inventaire`, `!shop`, `!acheter`, `!creation`, et la boucle de spawn |
| `combat_manager.py` | `CombatSession` : état du combat en cours (monstre commun, dégâts de chaque joueur, timers d'attaque toutes les 5s côté joueur et côté monstre, prévenance de 5s, fin de combat, loot) |
| `combat_utils.py` | Formules de dégâts et table des avantages élémentaires (feu > terre > foudre > eau > feu) |
| `economie_db.py` | Table `economie` : argent par joueur |
| `stats_db.py` | Table `player_stats` : hp, hp_max, attaque, defense, xp, niveau, points de stats à répartir |
| `inventory_db.py` | Table `inventory` : tous les objets possédés par chaque joueur (ton fichier d'origine, ré-indenté) |
| `equipement_db.py` | Table `equipement` : arme/armure actuellement portée + chargement des catalogues `armes.json` / `armures.json` |
| `armes.json` / `armures.json` | Catalogues statiques des équipements (stats, élément, prix, rareté) |
| `monstres.json` | Catalogue des monstres (hp, attaque, defense, élément, attaques détaillées, loot, argent, xp) |

## Points importants / à adapter

- **Un seul combat par serveur à la fois** : `GuildHuntState.session` — si tu veux plusieurs combats en parallèle (un par salon vocal par ex.), il faudra clé sur le salon plutôt que sur la guilde.
- **Détection "en vocal"** : `_quelquun_en_vocal()` regarde tous les salons vocaux du serveur. Adapte si tu veux limiter à un salon vocal précis.
- **`!soin`** consomme un objet nommé exactement `potion_soin` dans l'inventaire (ajouté via le shop). Le mapping potion → soin est dans `CATALOGUE_POTIONS` du fichier `monster_hunter.py`.
- **`!creation`** est une implémentation simple à base de recettes fixes (matériau de loot → équipement). À étoffer si tu veux plusieurs ingrédients, de l'argent en plus, etc.
- **Delete des messages** : chaque message envoyé pendant un combat est stocké dans `session.messages_a_supprimer` et supprimé à la fin du combat (victoire ou défaite). Les commandes des joueurs sont supprimées immédiatement après lecture.
- **`.env`** attendu à la racine avec :
  ```
  DISCORD_TOKEN=...
  DATABASE_URL=postgresql://...
  ```

## Lancer le bot

```bash
pip install -r requirements.txt
python bot.py
```

Crée un salon texte nommé `chasse` sur ton serveur : c'est là que les monstres apparaîtront et que les combats se dérouleront.
