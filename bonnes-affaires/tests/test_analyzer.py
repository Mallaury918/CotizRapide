import unittest

from dealbot.analyzer import analyze, is_relevant, market_price
from dealbot.config import DEFAULT_EXCLUDE, Settings, Watch
from dealbot.models import Listing
from dealbot.storage import Store

DAY = 86400


def L(i, price, title="iPhone 15 Pro 128 Go", source="ebay", shipping=0.0):
    return Listing(source, str(i), title, price, "EUR", f"https://x/{i}", shipping=shipping)


def watch(**kw):
    base = dict(name="iphone", query="iphone 15 pro", sources=["ebay"],
                must_include=["iphone", "15", "pro"], exclude=["max"] + DEFAULT_EXCLUDE)
    base.update(kw)
    return Watch(**base)


class MarketPriceTest(unittest.TestCase):
    def test_median_ignores_outliers(self):
        self.assertEqual(market_price([700, 710, 690, 720, 705, 1, 9999]), 705)

    def test_empty(self):
        self.assertIsNone(market_price([]))


class RelevanceTest(unittest.TestCase):
    def test_filters_accessories_and_other_models(self):
        w = watch()
        self.assertTrue(is_relevant(L(1, 700), w))
        self.assertFalse(is_relevant(L(2, 15, "Coque iPhone 15 Pro"), w))
        self.assertFalse(is_relevant(L(3, 900, "iPhone 15 Pro Max"), w))
        self.assertFalse(is_relevant(L(4, 300, "iPhone 15 Pro HS écran cassé"), w))
        self.assertFalse(is_relevant(L(5, 300, "iPhone 14 Pro"), w))

    def test_whole_word_match(self):
        w = watch(must_include=["hsbc"], exclude=["hs"])
        self.assertTrue(is_relevant(L(1, 10, "Carte HSBC"), w))


class AnalyzeTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.settings = Settings(min_samples=8)
        self.now = 1_000_000_000

    def seed_market(self, w, n=10, price=700):
        market = [L(f"m{i}", price + (i % 3) * 10) for i in range(n)]
        analyze(w, market, self.store, self.settings, now=self.now - DAY)

    def test_flags_below_market_and_price_error(self):
        w = watch()
        self.seed_market(w)
        deals = analyze(w, [L("a", 480), L("b", 150), L("c", 690)], self.store,
                        self.settings, now=self.now)
        kinds = {d.listing.item_id: d.kind for d in deals}
        self.assertEqual(kinds, {"b": "erreur_prix", "a": "sous_marche"})
        self.assertEqual(deals[0].listing.item_id, "b")  # la plus grosse remise d'abord
        self.assertTrue(deals[0].warnings)  # avertissement arnaque sur prix très bas

    def test_uses_reference_price_until_enough_samples(self):
        w = watch(reference_price=700)
        deals = analyze(w, [L("a", 450)], self.store, self.settings, now=self.now)
        self.assertEqual(len(deals), 1)
        self.assertIn("prix de référence", deals[0].reason)

    def test_no_reference_no_alert(self):
        deals = analyze(watch(), [L("a", 100)], self.store, self.settings, now=self.now)
        self.assertEqual(deals, [])

    def test_shipping_counts_in_price(self):
        w = watch(reference_price=700)
        deals = analyze(w, [L("a", 450, shipping=200)], self.store, self.settings, now=self.now)
        self.assertEqual(deals, [])

    def test_sudden_price_drop_on_same_item(self):
        w = watch(must_include=["ps5"], exclude=[])
        item = lambda p: L("sku1", p, "Console PS5 Slim", source="site:shop.fr")
        self.assertEqual(analyze(w, [item(499)], self.store, self.settings, now=self.now), [])
        deals = analyze(w, [item(49.9)], self.store, self.settings, now=self.now + 900)
        self.assertEqual(len(deals), 1)
        self.assertEqual(deals[0].kind, "erreur_prix")
        self.assertIn("499.00", deals[0].reason)

    def test_no_duplicate_alert_unless_cheaper(self):
        w = watch(reference_price=700)
        d1 = analyze(w, [L("a", 400)], self.store, self.settings, now=self.now)
        self.store.mark_alerted(d1[0].listing.key, d1[0].listing.total)
        self.assertEqual(analyze(w, [L("a", 400)], self.store, self.settings, now=self.now + 1), [])
        self.assertEqual(len(analyze(w, [L("a", 350)], self.store, self.settings,
                                     now=self.now + 2)), 1)

    def test_other_currency_ignored(self):
        w = watch(reference_price=700)
        l = L("a", 100)
        l.currency = "USD"
        self.assertEqual(analyze(w, [l], self.store, self.settings, now=self.now), [])


if __name__ == "__main__":
    unittest.main()
