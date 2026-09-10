import unittest
from pathlib import Path

from helpers.extractors import list_recipes


REPO_ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {
    ".git",
    "__pycache__",
    "browser_context",
    "browser_context_instances",
    "logs",
    "screenshots",
}
SOURCE_SUFFIXES = {".html", ".js", ".json", ".md", ".py", ".sh"}
FORBIDDEN_SITE_TERMS = (
    "link" + "edin",
    "you" + "tube",
    "what" + "sapp",
    "g" + "mail",
    "twit" + "ter",
    "face" + "book",
    "insta" + "gram",
    "red" + "dit",
    "spot" + "ify",
    "ycombi" + "nator",
)


class SiteAgnosticTests(unittest.TestCase):
    def test_only_generic_extraction_recipes_are_registered(self):
        self.assertEqual(list_recipes(), ["page_links", "page_meta"])

    def test_product_sources_do_not_name_target_sites(self):
        violations = []
        for path in REPO_ROOT.rglob("*"):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            if any(part in SKIP_DIRS for part in path.relative_to(REPO_ROOT).parts):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            matches = [term for term in FORBIDDEN_SITE_TERMS if term in text]
            if matches:
                violations.append(f"{path.relative_to(REPO_ROOT)}: {', '.join(matches)}")
        self.assertEqual(violations, [])

    def test_repository_paths_are_portable(self):
        forbidden_paths = (
            "." + "venv",
            "/" + "Users/",
            "C:" + "\\\\Users\\\\",
            "~" + "/",
        )
        violations = []
        for path in REPO_ROOT.rglob("*"):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            if any(part in SKIP_DIRS for part in path.relative_to(REPO_ROOT).parts):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            matches = [term for term in forbidden_paths if term in text]
            if matches:
                violations.append(f"{path.relative_to(REPO_ROOT)}: {', '.join(matches)}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
