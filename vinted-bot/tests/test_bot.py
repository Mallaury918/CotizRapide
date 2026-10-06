import random
import unittest

from vinted_bot import __main__ as bot
from vinted_bot.analyse import CRITERES_DEFAUT, evaluer, normaliser, passe_filtres, vendeur_fiable
from vinted_bot.client import VintedClient, params_depuis_url
from vinted_bot.flux import Flux, comparables, jetons
from vinted_bot.leboncoin import LeboncoinClient, normaliser_lbc, requete_recherche
from vinted_bot.stockage import Stockage


BON_VENDEUR = {"given_item_count": 12, "feedback_count": 9, "feedback_reputation": 0.96}


def item(id_, prix, titre="Nike Dunk Low Panda", marque="Nike", etat="Très bon état", vendeur=7):
    return {"id": id_, "title": titre, "price": {"amount": f"{prix:.1f}", "currency_code": "EUR"},
            "brand_title": marque, "status": etat, "size_title": "42",
            "url": f"https://www.vinted.fr/items/{id_}", "photo": {"url": ""},
            "user": {"id": vendeur, "login": f"membre{vendeur}"}, "favourite_count": 2}


class ProfilsMixin(VintedClient):
    profils = {}
    profils_lus = 0

    def utilisateur(self, id_):
        self.profils_lus += 1
        return self.profils.get(id_, BON_VENDEUR)


class FauxClient(ProfilsMixin):
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


CRIT = {**CRITERES_DEFAUT, "mots_exclus": ["cassé", "boîte vide"]}


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
        self.assertEqual(p, {"search_text": "nike dunk", "attribute_ids[brand]": "53,14",
                             "attribute_ids[status]": "6", "price_to": "50"})

    def test_filtres_vides_ignores(self):
        p = params_depuis_url("https://www.vinted.fr/catalog?search_text=pull&price_from=&catalog_ids=1904")
        self.assertEqual(p, {"search_text": "pull", "attribute_ids[catalog]": "1904"})


class TestFormat2026(unittest.TestCase):
    """Format de svc-catalogue : marque/taille/état dans item_box, lien relatif."""

    def test_item_box(self):
        a = normaliser({
            "id": 42, "title": "Dunk Low Panda", "price": {"amount": "45.0", "currency_code": "EUR"},
            "url": "/items/42-dunk-low-panda", "photo": {"url": "https://img/1.jpg"},
            "user": {"id": 9, "login": "zoe"},
            "item_box": {"first_line": "Nike", "second_line": "42 · Très bon état"},
        })
        self.assertEqual((a.marque, a.taille, a.etat), ("Nike", "42", "Très bon état"))
        self.assertEqual(a.url, "https://www.vinted.fr/items/42-dunk-low-panda")
        self.assertEqual(a.vendeur_id, 9)

    def test_item_box_sans_taille(self):
        a = normaliser({"id": 1, "title": "Switch OLED", "price": "250",
                        "item_box": {"first_line": "Nintendo", "second_line": "Neuf sans étiquette"}})
        self.assertEqual((a.marque, a.taille, a.etat), ("Nintendo", "", "Neuf sans étiquette"))
        a = normaliser({"id": 1, "title": "Pull", "price": "10", "item_box": {}})
        self.assertEqual((a.marque, a.taille, a.etat), ("", "", ""))


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
        self.assertEqual(notif.recues[0].profil.ventes, 12)


class TestVendeurs(unittest.TestCase):
    def passage(self, profils, conf_criteres=None):
        rnd = random.Random(4)
        marche = [item(i, rnd.uniform(60, 90), vendeur=1) for i in range(1, 150)]
        recherche = {"nom": "Dunk", "mots_cles": "nike dunk"}
        conf = {"recherches": [recherche], "criteres": conf_criteres or {}}
        stock, notif = Stockage(":memory:"), FauxNotif()
        client = FauxClient(marche, marche[:5])
        client.profils = profils
        bot.traiter_recherche(recherche, conf, client, stock, notif)
        client.nouvelles = [item(601, 20, vendeur=10), item(602, 21, vendeur=11),
                            item(603, 22, vendeur=12), item(604, 23, vendeur=13), item(605, 24, vendeur=10)]
        bot.traiter_recherche(recherche, conf, client, stock, notif)
        return [a.annonce.id for a in notif.recues], client

    def test_filtre_par_defaut(self):
        profils = {
            10: BON_VENDEUR,
            11: {"given_item_count": 0, "feedback_count": 3, "feedback_reputation": 1},  # aucune vente
            12: {"given_item_count": 4, "feedback_count": 0},                            # aucun avis
            13: {},                                                                      # profil neuf
        }
        ids, client = self.passage(profils)
        self.assertEqual(ids, [601, 605])
        self.assertEqual(client.profils_lus, 4)   # le vendeur 10 n'est lu qu'une fois (cache)

    def test_note_minimale(self):
        profils = {10: BON_VENDEUR, 11: {**BON_VENDEUR, "feedback_reputation": 0.7}}
        ids, _ = self.passage(profils, {"vendeur_note_min": 4.5})
        self.assertEqual(ids, [601, 603, 604, 605])

    def test_filtre_desactivable(self):
        ids, client = self.passage({11: {}}, {"vendeur_ventes_min": 0, "vendeur_avis_min": 0,
                                                "vendeur_note_min": 0})
        self.assertEqual(len(ids), 5)
        self.assertEqual(client.profils_lus, 0)

    def test_seuils_par_defaut_5_ventes_4_etoiles(self):
        profils = {
            10: {"given_item_count": 5, "feedback_count": 4, "feedback_reputation": 0.8},   # 5 ventes, 4/5
            11: {"given_item_count": 4, "feedback_count": 9, "feedback_reputation": 1},     # 4 ventes
            12: {"given_item_count": 30, "feedback_count": 20, "feedback_reputation": 0.7},  # 3,5/5
            13: {"given_item_count": 8, "feedback_count": 0, "feedback_reputation": 0},     # aucun avis
        }
        ids, _ = self.passage(profils)
        self.assertEqual(ids, [601, 605])

    def test_profil_illisible(self):
        class Panne(FauxClient):
            def utilisateur(self, id_):
                raise OSError("réseau")
        stock, notif = Stockage(":memory:"), FauxNotif()
        hist = [(i, 70.0, "Nike", "Très bon état") for i in range(1, 40)]
        from vinted_bot.vendeurs import verifier_vendeur
        aff = evaluer(normaliser(item(999, 20)), hist, CRIT)
        self.assertFalse(verifier_vendeur(aff, Panne([], []), stock, CRIT))


class FauxFlux(ProfilsMixin):
    """Simule le flux « nouveautés » de tout Vinted : chaque appel renvoie le lot suivant."""

    def __init__(self):
        self.lots = []

    def rechercher(self, params, ordre="newest_first", page=1, par_page=96):
        self.appels = getattr(self, "appels", 0) + 1
        return self.lots[page - 1] if page <= len(self.lots) else []


class TestFlux(unittest.TestCase):
    def test_jetons(self):
        self.assertEqual(jetons("Nike Dunk Low Panda taille 42 TBE", "Nike", "42"), {"dunk", "low", "panda"})
        self.assertEqual(jetons("T-shirt Ralph Lauren T.38", "Ralph Lauren", "M"), {"tshirt"})

    def test_comparables(self):
        dunk = {"dunk", "low", "panda"}
        self.assertTrue(comparables(dunk, {"baskets", "dunk", "low", "panda"}))
        self.assertTrue(comparables(dunk, {"dunk", "low"}))
        self.assertFalse(comparables({"chaussettes", "dunk", "panda"}, dunk))
        self.assertFalse(comparables({"coque", "iphone", "15"}, {"iphone", "15", "128"}))
        self.assertFalse(comparables({"pull", "col", "rond"}, {"polo", "col", "rond"}))
        self.assertFalse(comparables({"air", "max", "90"}, dunk))

    def test_flux_complet(self):
        rnd = random.Random(3)
        n = iter(range(1000, 100000))
        conf = {"flux": {"actif": True, "pages_max": 2}, "criteres": {"mots_exclus": ["cassé"]}}
        flux, stock, notif, client = Flux(conf), Stockage(":memory:"), FauxNotif(), FauxFlux()

        # Le marché : des Dunk entre 60 et 90 €, des chaussettes Dunk entre 8 et 12 €
        marche = [item(next(n), rnd.uniform(60, 90), titre="Nike Dunk Low Panda") for _ in range(30)]
        marche += [item(next(n), rnd.uniform(8, 12), titre="Chaussettes Nike Dunk Panda") for _ in range(30)]
        marche += [item(next(n), 30, titre="Pull vintage", marque="") for _ in range(20)]
        client.lots = [list(reversed(marche))]
        flux.passage(client, stock, notif)
        self.assertEqual(stock.taille_flux(), 60)   # les annonces sans marque sont ignorées
        self.assertEqual(notif.recues, [])

        # Nouveautés : vraie affaire, chaussettes à prix normal, Dunk cassées
        nouvelles = [item(next(n), 22, titre="Baskets Nike Dunk Low Panda"),
                     item(next(n), 6, titre="Chaussettes Nike Dunk Panda"),
                     item(next(n), 15, titre="Nike Dunk Low Panda cassé")]
        client.lots = [list(reversed(nouvelles)) + client.lots[0][:10]]
        flux.passage(client, stock, notif)
        self.assertEqual([a.annonce.titre for a in notif.recues], ["Baskets Nike Dunk Low Panda"])
        self.assertIn("titres proches", notif.recues[0].groupe)

        # Repassage : aucune alerte en double
        flux.passage(client, stock, notif)
        self.assertEqual(len(notif.recues), 1)

    def test_lecture_de_plusieurs_pages_si_retard(self):
        stock, client = Stockage(":memory:"), FauxFlux()
        flux = Flux({"flux": {"pages_max": 3}})
        client.lots = [[item(100, 50)]]
        flux.passage(client, stock, FauxNotif())
        # Deux pages entières sans retrouver l'annonce 100 → le bot lit la page suivante
        client.appels = 0
        client.lots = [[item(300, 50)], [item(200, 50)], [item(100, 50)]]
        flux.passage(client, stock, FauxNotif())
        self.assertEqual(client.appels, 3)
        self.assertEqual(stock.taille_flux(), 3)

    def test_nettoyage(self):
        stock = Stockage(":memory:")
        a = normaliser(item(1, 50))
        stock.enregistrer_flux([(a, {"dunk", "low"})])
        stock.db.execute("UPDATE flux SET vu_le = 0")
        stock.nettoyer_flux(10)
        self.assertEqual(stock.taille_flux(), 0)
        self.assertEqual(stock.db.execute("SELECT COUNT(*) FROM flux_jetons").fetchone()[0], 0)


def ad_lbc(id_, prix, titre="Nintendo Switch OLED blanche", marque="Nintendo", etat="Très bon état",
           vendeur="u-1", expediable="true"):
    return {"list_id": id_, "subject": titre, "price": [int(prix)], "price_cents": int(prix * 100),
            "url": f"https://www.leboncoin.fr/ad/consoles/{id_}", "category_id": "43",
            "images": {"urls_large": [f"https://img.leboncoin.fr/{id_}.jpg"]},
            "owner": {"user_id": vendeur, "type": "private", "name": f"vendeur-{vendeur}"},
            "counters": {"favorites": 4},
            "attributes": [{"key": "brand", "value": marque.lower(), "value_label": marque},
                           {"key": "condition", "value": "tresbonetat", "value_label": etat},
                           {"key": "shippable", "value": expediable}]}


class FauxLbc(LeboncoinClient):
    def __init__(self, marche, nouvelles, profils=None):
        self.livraison, self.marche, self.nouvelles = True, marche, nouvelles
        self.profils, self.requetes = profils or {}, []

    def rechercher(self, requete):
        self.requetes.append(requete)
        if requete["sort_by"] == "relevance":
            debut = requete["offset"]
            return self.marche[debut: debut + requete["limit"]]
        return self.nouvelles

    def requete(self, methode, url, json=None):
        user_id = url.split("/v2/")[1].split("/")[0]
        return self.profils.get(user_id, {"feedback": {"overall_score": 0.94, "received_count": 12}})


class TestLeboncoin(unittest.TestCase):
    def test_normalisation(self):
        a = normaliser_lbc(ad_lbc(77, 180.5))
        self.assertEqual((a.id, a.prix, a.marque, a.etat), (77, 180.5, "Nintendo", "Très bon état"))
        self.assertEqual((a.vendeur_id, a.vendeur, a.catalogue), ("u-1", "vendeur-u-1", 43))
        self.assertEqual(a.photo, "https://img.leboncoin.fr/77.jpg")
        self.assertIsNone(normaliser_lbc({"list_id": 1, "subject": "Don", "price": [0]}))

    def test_frais_reels(self):
        ad = ad_lbc(1, 80)
        ad["buyer_fee"] = {"amount": 199}
        ad["shipping_fees"] = [{"shipping_type": "colissimo", "price": 590},
                               {"shipping_type": "mondial_relay", "price": 249}]
        a = normaliser_lbc(ad)
        self.assertEqual((a.prix_total, a.livraison), (81.99, 2.49))
        hist = [(i, 160.0, "Nintendo", "Très bon état") for i in range(2, 40)]
        aff = evaluer(a, hist, {**CRITERES_DEFAUT, "frais_livraison_achat": 6})
        self.assertEqual(aff.cout_total, 84.48)          # le vrai port remplace l'estimation
        # Sans frais indiqués : estimation de la protection, port fixé par la configuration
        b = normaliser_lbc(ad_lbc(2, 80))
        self.assertEqual((b.prix_total, b.livraison), (84.7, None))

    def test_marque_reelle_et_pas_leboncoin(self):
        ad = ad_lbc(1, 80)
        ad["brand"] = "leboncoin"
        ad["attributes"] = [{"key": "console_brand", "value": "nintendo", "value_label": "Nintendo"},
                            {"key": "condition", "value_label": "État neuf"}]
        self.assertEqual(normaliser_lbc(ad).marque, "Nintendo")
        ad["attributes"] = []
        self.assertEqual(normaliser_lbc(ad).marque, "")

    def test_requete_livraison_toute_la_france(self):
        r = requete_recherche({"mots_cles": "switch oled"}, {"prix_min": 100, "prix_max": 300},
                              recentes=True, page=2, par_page=35, livraison=True)
        self.assertEqual(r["filters"]["location"], {"shippable": True})
        self.assertNotIn("locations", r["filters"]["location"])
        self.assertEqual(r["filters"]["ranges"]["price"], {"min": 100, "max": 300})
        self.assertEqual(r["filters"]["keywords"], {"text": "switch oled"})
        self.assertEqual((r["sort_by"], r["sort_order"], r["offset"]), ("time", "desc", 35))

    def test_requete_depuis_url(self):
        r = requete_recherche({"url": "https://www.leboncoin.fr/recherche?category=43&text=ps5"
                                      "&locations=Lyon__45.7_4.8_5000&price=200-400&shippable=1"},
                              {}, recentes=False, page=1, par_page=35, livraison=True)
        f = r["filters"]
        self.assertEqual((f["category"], f["keywords"]), ({"id": "43"}, {"text": "ps5"}))
        self.assertEqual(f["ranges"]["price"], {"min": 200, "max": 400})
        self.assertEqual(f["location"], {"shippable": True})   # la ville de l'URL est ignorée
        self.assertEqual(r["sort_by"], "relevance")

    def test_profil_sans_nombre_de_ventes(self):
        client = FauxLbc([], [], {"u-2": {"feedback": {"overall_score": 0.9, "received_count": 3}}})
        p = client.profil("u-2")
        self.assertEqual((p.avis, p.note, p.ventes_connues), (3, 4.5, False))
        crit = {"vendeur_ventes_min": 5, "vendeur_avis_min": 1, "vendeur_note_min": 4}
        self.assertFalse(vendeur_fiable(p, crit))   # 3 avis < 5 exigés
        self.assertTrue(vendeur_fiable(client.profil("u-1"), crit))

    def test_parcours_complet(self):
        rnd = random.Random(5)
        marche = [ad_lbc(i, rnd.uniform(200, 260)) for i in range(1, 80)]
        conf = {"leboncoin": {"actif": True, "recherches": [{"nom": "Switch", "mots_cles": "switch oled"}],
                              "mots_exclus": ["manette"]}}
        recherche = conf["leboncoin"]["recherches"][0]
        stock, notif = Stockage(":memory:"), FauxNotif()
        client = FauxLbc(marche, marche[:5], {"u-9": {"feedback": {"overall_score": 1, "received_count": 1}}})
        bot.passage_leboncoin(conf, client, stock, notif)
        self.assertEqual(notif.recues, [])
        client.nouvelles = [ad_lbc(901, 95), ad_lbc(902, 90, titre="Manette Switch OLED"),
                            ad_lbc(903, 90, vendeur="u-9"), ad_lbc(904, 90, expediable="false")]
        bot.passage_leboncoin(conf, client, stock, notif)
        self.assertEqual([a.annonce.id for a in notif.recues], [901])
        self.assertTrue(all(r["filters"]["location"] == {"shippable": True} for r in client.requetes))
        # Les recherches Vinted et Leboncoin ne partagent pas leur mémoire
        self.assertTrue(stock.connait_recherche("Leboncoin · Switch"))
        self.assertFalse(stock.connait_recherche("Switch"))


if __name__ == "__main__":
    unittest.main()
