"""Run with python -m unittest tests.test_public_base_url (no database needed)."""
import ast
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]


def load_function(path, name, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8-sig"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, "exec"), namespace)
    return namespace[name]


resolve = load_function("app/seller_config.py", "_resolve_base_url", {})


class PublicURLTests(unittest.TestCase):
    def test_retired_ip(self):
        for url in ["http://165.101.65.175", "https://165.101.65.175/",
                    "http://165.101.65.175:8000", "165.101.65.175"]:
            with self.subTest(url=url):
                self.assertEqual(resolve(url, ""), "https://www.easy-ekkasan.com")

    def test_environment_overrides_local(self):
        self.assertEqual(resolve("http://165.101.65.175", "https://staging.example.test/"),
                         "https://staging.example.test")

    def test_retired_environment_value(self):
        self.assertEqual(resolve("", "http://165.101.65.175"), "https://www.easy-ekkasan.com")

    def test_empty_and_production_domain(self):
        for url in ["", "http://easy-ekkasan.com", "https://www.easy-ekkasan.com/"]:
            self.assertEqual(resolve(url, ""), "https://www.easy-ekkasan.com")

    def test_local_development_preserved(self):
        self.assertEqual(resolve("http://127.0.0.1:8000/", ""), "http://127.0.0.1:8000")

    def test_verification_and_checkout_flow_preserved(self):
        fn = load_function("app/routers/sales.py", "_verify_link", {
            "Request": object, "SELLER": {"base_url": resolve("http://165.101.65.175", "")}})
        url = fn(object(), "test-token+value", "test-flow")
        self.assertEqual(urlsplit(url).netloc, "www.easy-ekkasan.com")
        self.assertEqual(urlsplit(url).path, "/verify")
        self.assertEqual(parse_qs(urlsplit(url).query),
                         {"token": ["test-token+value"], "flow": ["test-flow"]})

    def test_password_reset_uses_domain(self):
        import sys
        import types
        from unittest.mock import patch
        config = types.ModuleType("app.seller_config")
        config.SELLER = {"base_url": resolve("http://165.101.65.175", "")}
        fn = load_function("app/routers/auth.py", "_abs_link", {"Request": object})
        with patch.dict(sys.modules, {"app.seller_config": config}):
            self.assertEqual(fn(object(), "/reset?token=test-token"),
                             "https://www.easy-ekkasan.com/reset?token=test-token")


if __name__ == "__main__":
    unittest.main()
