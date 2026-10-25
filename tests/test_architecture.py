"""The brief's constraint: domain logic must not depend on Shopify; Shopify is reached through an adapter."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "pos"


def imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


class TestBoundaries(unittest.TestCase):
    def test_domain_and_services_never_import_adapters(self):
        offenders = []
        for folder in ("domain", "services"):
            for f in (ROOT / folder).glob("*.py"):
                for mod in imports(f):
                    if mod.startswith("pos.adapters") or "shopify" in mod.lower():
                        offenders.append(f"{f.relative_to(ROOT)} imports {mod}")
        self.assertEqual(offenders, [], "core code must not know about adapters or Shopify")

    def test_only_the_shopify_adapter_and_the_composition_root_mention_shopify_modules(self):
        allowed = {"adapters/shopify_adapter.py", "bootstrap.py"}
        for f in ROOT.rglob("*.py"):
            rel = f.relative_to(ROOT).as_posix()
            if any("shopify_adapter" in m for m in imports(f)):
                self.assertIn(rel, allowed, f"{rel} should not import the Shopify adapter")

    def test_no_float_arithmetic_on_money_in_the_domain(self):
        # money must be integer paise: no `float(` and no division by 10000.0 in domain code
        for f in (ROOT / "domain").glob("*.py"):
            src = f.read_text(encoding="utf-8")
            self.assertNotIn("10000.0", src, f.name)
            self.assertNotIn("round(", src, f.name)


if __name__ == "__main__":
    unittest.main()
