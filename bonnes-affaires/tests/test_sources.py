import unittest

from dealbot.sources import ebay
from dealbot.sources.sites import extract_listings, parse_price

PRODUCT_PAGE = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"BreadcrumbList"},
  {"@type":"Product","name":"Console PS5 Slim","sku":"PS5-SLIM","image":["https://i/1.jpg"],
   "offers":{"@type":"Offer","price":"449,99","priceCurrency":"EUR",
             "availability":"https://schema.org/InStock"}}
]}
</script></head><body></body></html>
"""

CATEGORY_PAGE = """
<script type="application/ld+json">
{"@type":"ItemList","itemListElement":[
  {"@type":"ListItem","item":{"@type":"Product","name":"Casque A","url":"/casque-a",
    "offers":{"@type":"Offer","price":99,"priceCurrency":"EUR"}}},
  {"@type":"ListItem","item":{"@type":"Product","name":"Casque B","url":"/casque-b",
    "offers":{"@type":"AggregateOffer","lowPrice":"1 249.50","priceCurrency":"EUR"}}},
  {"@type":"ListItem","item":{"@type":"Product","name":"Casque C","url":"/casque-c",
    "offers":{"@type":"Offer","price":10,"availability":"https://schema.org/OutOfStock"}}}
]}
</script>
"""

OG_PAGE = """
<meta property="og:title" content="Robot cuiseur">
<meta property="product:price:amount" content="199.00">
<meta property="product:price:currency" content="EUR">
"""


class SitesTest(unittest.TestCase):
    def test_product_page(self):
        [l] = extract_listings(PRODUCT_PAGE, "https://www.shop.fr/ps5")
        self.assertEqual((l.title, l.price, l.item_id, l.source),
                         ("Console PS5 Slim", 449.99, "PS5-SLIM", "site:shop.fr"))
        self.assertEqual(l.image, "https://i/1.jpg")

    def test_category_page_skips_out_of_stock(self):
        ls = extract_listings(CATEGORY_PAGE, "https://shop.fr/casques")
        self.assertEqual([(l.title, l.price) for l in ls], [("Casque A", 99), ("Casque B", 1249.5)])
        self.assertEqual(ls[0].url, "https://shop.fr/casque-a")

    def test_open_graph_fallback(self):
        [l] = extract_listings(OG_PAGE, "https://shop.fr/robot")
        self.assertEqual((l.title, l.price), ("Robot cuiseur", 199.0))

    def test_parse_price(self):
        for raw, expected in [("1 299,99 €", 1299.99), ("1,299.99", 1299.99), ("12,5", 12.5),
                              ("1,299", 1299.0), (35, 35.0), ("", None), ("gratuit", None)]:
            self.assertEqual(parse_price(raw), expected, raw)


class EbayTest(unittest.TestCase):
    def test_parse_item(self):
        l = ebay.parse_item({
            "itemId": "v1|123|0", "title": "iPhone 15 Pro", "condition": "Occasion",
            "price": {"value": "650.00", "currency": "EUR"},
            "shippingOptions": [{"shippingCost": {"value": "8.50", "currency": "EUR"}}],
            "itemWebUrl": "https://www.ebay.fr/itm/123",
        })
        self.assertEqual((l.price, l.shipping, l.total), (650.0, 8.5, 658.5))

    def test_seller_account_type(self):
        base = {"itemId": "1", "title": "x", "price": {"value": "10", "currency": "EUR"}}
        pro = ebay.parse_item({**base, "seller": {"sellerAccountType": "BUSINESS"}})
        perso = ebay.parse_item({**base, "seller": {"sellerAccountType": "INDIVIDUAL"}})
        unknown = ebay.parse_item(base)
        self.assertEqual((pro.seller_pro, perso.seller_pro, unknown.seller_pro), (True, False, None))
        self.assertTrue(ebay.seller_is_pro({"sellerLegalInfo": {"legalContactFirstName": "A"}}))

    def test_verify_seller_reads_full_item(self):
        class S:
            def get_json(self, url, **kw):
                self.url = url
                return {"seller": {"sellerAccountType": "INDIVIDUAL"}}
        src = ebay.EbaySource(S(), "id", "secret")
        src._token, src._expires = "t", float("inf")
        l = ebay.parse_item({"itemId": "v1|123|0", "title": "x", "price": {"value": "10"}})
        src.verify_seller(l)
        self.assertFalse(l.seller_pro)
        self.assertTrue(src.session.url.endswith("/item/v1%7C123%7C0"))

    def test_missing_price(self):
        self.assertIsNone(ebay.parse_item({"itemId": "1", "title": "x"}))


if __name__ == "__main__":
    unittest.main()
