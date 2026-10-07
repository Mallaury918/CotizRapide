import tempfile
import unittest
from pathlib import Path

from dealbot.telegram_setup import find_chat_id, save_chat_id


class FakeSession:
    def __init__(self, data):
        self.data = data

    def get_json(self, url, **kw):
        self.url = url
        return self.data


class TelegramSetupTest(unittest.TestCase):
    def test_find_latest_chat(self):
        s = FakeSession({"ok": True, "result": [
            {"update_id": 1, "message": {"chat": {"id": 111, "first_name": "Ancien"}}},
            {"update_id": 2, "message": {"chat": {"id": 987654321, "first_name": "Mallaury"},
                                         "text": "/start"}},
        ]})
        self.assertEqual(find_chat_id("TOKEN", s), ("987654321", "Mallaury"))
        self.assertTrue(s.url.endswith("/botTOKEN/getUpdates"))

    def test_no_message(self):
        self.assertIsNone(find_chat_id("T", FakeSession({"ok": True, "result": []})))

    def test_save_only_in_telegram_section(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text('[general]\nchat_id = "x"\n\n[telegram]\ntoken = "abc"\n'
                         'chat_id = ""   # commentaire\n\n[ebay]\n', encoding="utf-8")
            self.assertTrue(save_chat_id(p, "42"))
            text = p.read_text(encoding="utf-8")
            self.assertIn('[general]\nchat_id = "x"', text)
            self.assertIn('[telegram]\ntoken = "abc"\nchat_id = "42"   # commentaire', text)


if __name__ == "__main__":
    unittest.main()
