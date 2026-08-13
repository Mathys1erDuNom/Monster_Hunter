# combat_utils.py
"""
Formules de dégâts et table des éléments pour le bot Monster Hunter.

Dégat_infligée = (attaque_perso * degat_arme * multiplicateur_type) / defense_monstre
Dégat_reçu     = (attaque_monstre * multiplicateur_type * degat_base_attaque) / defense_joueur
"""

# Table des avantages élémentaires : feu > terre > foudre > eau > feu (cycle)
# valeur > 1  : l'attaquant est avantagé
# valeur < 1  : l'attaquant est désavantagé
# valeur == 1 : neutre
AVANTAGES = {
    "feu": "terre",
    "terre": "foudre",
    "foudre": "eau",
    "eau": "feu",
}

DESAVANTAGES = {v: k for k, v in AVANTAGES.items()}

MULTIPLICATEUR_AVANTAGE = 1.5
MULTIPLICATEUR_DESAVANTAGE = 0.75


def multiplicateur_element(element_attaquant, element_defenseur):
    """Retourne le multiplicateur de dégâts en fonction des éléments en présence."""
    if element_attaquant == "neutre" or element_defenseur == "neutre":
        return 1.0
    if AVANTAGES.get(element_attaquant) == element_defenseur:
        return MULTIPLICATEUR_AVANTAGE
    if DESAVANTAGES.get(element_attaquant) == element_defenseur:
        return MULTIPLICATEUR_DESAVANTAGE
    return 1.0


def degat_infliges_au_monstre(attaque_perso, degat_arme, element_arme, element_monstre, defense_monstre):
    """Calcule les dégâts infligés par un joueur au monstre."""
    mult = multiplicateur_element(element_arme, element_monstre)
    defense = max(defense_monstre, 1)
    degat = (attaque_perso * degat_arme * mult) / defense
    return max(round(degat), 1)


def degat_recus_par_joueur(attaque_monstre, element_attaque_monstre, degat_base_attaque, element_armure, defense_joueur):
    """Calcule les dégâts reçus par un joueur suite à une attaque du monstre."""
    mult = multiplicateur_element(element_attaque_monstre, element_armure)
    defense = max(defense_joueur, 1)
    degat = (attaque_monstre * mult * degat_base_attaque) / defense
    return max(round(degat), 1)
