import unittest

from dealbot.sources import ebay, vinted
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

    def test_missing_price(self):
        self.assertIsNone(ebay.parse_item({"itemId": "1", "title": "x"}))


class VintedTest(unittest.TestCase):
    def test_parse_item_both_price_formats(self):
        a = vinted.parse_item({"id": 1, "title": "Switch OLED", "brand_title": "Nintendo",
                               "price": {"amount": "180.0", "currency_code": "EUR"},
                               "url": "https://www.vinted.fr/items/1-switch"})
        b = vinted.parse_item({"id": 2, "title": "Switch", "price": "150.0", "currency": "EUR"})
        self.assertEqual((a.price, a.title), (180.0, "Switch OLED Nintendo"))
        self.assertEqual((b.price, b.url), (150.0, "https://www.vinted.fr/items/2"))


if __name__ == "__main__":
    unittest.main()
