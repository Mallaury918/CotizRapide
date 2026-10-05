import random
import unittest

from vinted_bot import __main__ as bot
from vinted_bot.analyse import evaluer, normaliser, passe_filtres
from vinted_bot.client import params_depuis_url
from vinted_bot.stockage import Stockage


def item(id_, prix, titre="Nike Dunk Low Panda", marque="Nike", etat="Très bon état"):
    return {"id": id_, "title": titre, "price": {"amount": f"{prix:.1f}", "currency_code": "EUR"},
            "brand_title": marque, "status": etat, "size_title": "42",
            "url": f"https://www.vinted.fr/items/{id_}", "photo": {"url": ""},
            "user": {"login": "x"}, "favourite_count": 2}


class FauxClient:
    def __init__(self, marche, nouvelles):
        self.marche, self.nouvelles = marche, nouvelles

    def rechercher(self, params, ordre="newest_first", page=1, par_page=96):
        if ordre == "relevance":
            return self.marche[(page - 1) * 96: page * 96]
        return self.nouvelles


class FauxNotif:
    def __init__(self):
        self.recues = []

    def envoyer(self, aff, recherche):
        self.recues.append(aff)


CRIT = {**bot.CRITERES_DEFAUT, "mots_exclus": ["cassé", "boîte vide"]}


class TestAnalyse(unittest.TestCase):
    def setUp(self):
        rnd = random.Random(1)
        self.hist = [(i, rnd.uniform(60, 90), "Nike", "Très bon état") for i in range(1, 60)]

    def test_prix_formats(self):
        self.assertEqual(normaliser({"id": 1, "price": "12,5"}).prix, 12.5)
        a = normaliser({"id": 1, "price": {"amount": "20.0"}, "total_item_price": {"amount": "21.7"}})
        self.assertEqual(a.prix_total, 21.7)
        self.assertEqual(normaliser({"id": 1, "price": {"amount": "20.0"}}).prix_total, 21.7)
        self.assertIsNone(normaliser({"id": 1, "price": None}))

    def test_bonne_affaire_detectee(self):
        aff = evaluer(normaliser(item(999, 25)), self.hist, CRIT)
        self.assertIsNotNone(aff)
        self.assertGreater(aff.remise, 0.5)
        self.assertEqual(aff.groupe, "Nike · Très bon état")
        self.assertFalse(aff.suspect)

    def test_prix_normal_ignore(self):
        self.assertIsNone(evaluer(normaliser(item(999, 70)), self.hist, CRIT))

    def test_prix_suspect(self):
        self.assertTrue(evaluer(normaliser(item(999, 5)), self.hist, CRIT).suspect)

    def test_mots_exclus_sans_accents(self):
        a = normaliser(item(999, 25, titre="Dunk low CASSE semelle"))
        self.assertFalse(passe_filtres(a, {"mots_exclus": ["cassé"]}))
        a = normaliser(item(999, 25, titre="Dunk avec boite vide"))
        self.assertFalse(passe_filtres(a, {"mots_exclus": ["boîte vide"]}))
        # "hs" ne doit pas exclure "shorts"
        self.assertTrue(passe_filtres(normaliser(item(9, 25, titre="shorts")), {"mots_exclus": ["hs"]}))

    def test_pas_assez_de_comparables(self):
        self.assertIsNone(evaluer(normaliser(item(999, 25)), self.hist[:5], CRIT))

    def test_repli_sur_la_marque(self):
        aff = evaluer(normaliser(item(999, 25, etat="Neuf avec étiquette")), self.hist, CRIT)
        self.assertEqual(aff.groupe, "Nike")


class TestUrl(unittest.TestCase):
    def test_conversion(self):
        p = params_depuis_url("https://www.vinted.fr/catalog?search_text=nike%20dunk"
                              "&brand_ids[]=53&brand_ids[]=14&status_ids[]=6&price_to=50&catalog[]=1")
        self.assertEqual(p, {"search_text": "nike dunk", "brand_ids": "53,14",
                             "status_ids": "6", "price_to": "50"})


class TestBoucle(unittest.TestCase):
    def test_parcours_complet(self):
        rnd = random.Random(2)
        marche = [item(i, rnd.uniform(60, 90)) for i in range(1, 150)]
        recherche = {"nom": "Dunk", "mots_cles": "nike dunk"}
        conf = {"recherches": [recherche], "criteres": {"mots_exclus": ["cassé"]}}
        stock, notif = Stockage(":memory:"), FauxNotif()

        # 1er passage : initialisation, aucune alerte même pour une affaire déjà en ligne
        client = FauxClient(marche, [item(500, 20)] + marche[:10])
        bot.traiter_recherche(recherche, conf, client, stock, notif)
        self.assertEqual(notif.recues, [])

        # 2e passage : une affaire, une annonce cassée, une au prix normal
        client.nouvelles = [item(501, 22), item(502, 15, titre="Dunk cassé"), item(503, 75), item(500, 20)]
        bot.traiter_recherche(recherche, conf, client, stock, notif)
        self.assertEqual([a.annonce.id for a in notif.recues], [501])

        # 3e passage : rien de neuf → pas de doublon
        bot.traiter_recherche(recherche, conf, client, stock, notif)
        self.assertEqual(len(notif.recues), 1)


if __name__ == "__main__":
    unittest.main()
