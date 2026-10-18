"""The Design Foundation's files stay in step (docs/design/foundation/, AVR-424).

Two things are checked, offline and with the standard library only:

- the mirrored files (README.md, tokens.json) match MIRROR.sha256, the record the Media
  repository carries too, so neither copy changes without the other being told;
- every Party colour role in tokens.json has the value the shell's stylesheet really uses.
"""
import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOUNDATION = ROOT / "docs" / "design" / "foundation"

# foundation role -> the custom property in web/src/party.css that implements it
PARTY_ROLES = {
    "surface": "--color-base-100",
    "surface_low": "--color-base-200",
    "surface_raised": "--color-base-300",
    "on_surface": "--color-base-content",
    "on_surface_muted": "--color-muted",
    "on_surface_faint": "--color-faint",
    "outline_quiet": "--color-line",
    "outline_control": "--color-control",
    "outline_strong": "--color-line-strong",
    "action": "--color-primary",
    "on_action": "--color-primary-content",
    "accent": "--color-accent",
    "on_accent": "--color-accent-content",
    "selected": "--color-select",
    "status_warn": "--color-warning",
    "status_error": "--color-error",
    "material": "--color-material",
    "material_solid": "--color-material-solid",
    "material_edge": "--color-material-edge",
}


def digest(path):
    """SHA-256 of a text file with LF line ends, whatever core.autocrlf did to the checkout."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def squash(value):
    return re.sub(r"\s+", " ", value.strip().lower())


class MirrorTest(unittest.TestCase):
    def test_mirrored_files_match_their_record(self):
        recorded = dict(reversed(line.split()) for line in (FOUNDATION / "MIRROR.sha256").read_text().splitlines() if line.strip())
        self.assertEqual(set(recorded), {"README.md", "tokens.json"})
        for name, want in recorded.items():
            self.assertEqual(digest(FOUNDATION / name), want, f"{name} changed: update MIRROR.sha256 here and in the Media repository")


class PartyTokensTest(unittest.TestCase):
    def setUp(self):
        self.tokens = json.loads((FOUNDATION / "tokens.json").read_text(encoding="utf-8"))
        css = (ROOT / "web" / "src" / "party.css").read_text(encoding="utf-8")
        # the theme and @theme blocks come first; the contrast override later must not win
        css = css.split("@layer base")[0]
        self.css = {name: squash(value) for name, value in re.findall(r"(--[\w-]+):\s*([^;]+);", css)}

    def test_every_theme_defines_every_role(self):
        roles = set(self.tokens["roles"])
        for theme in self.tokens["themes"].values():
            self.assertLessEqual(roles, set(theme["color"]))

    def test_party_roles_are_the_stylesheets_values(self):
        party = self.tokens["themes"]["party"]["color"]
        for role, prop in PARTY_ROLES.items():
            self.assertIn(prop, self.css, prop)
            self.assertEqual(squash(party[role]), self.css[prop], f"{role} and {prop} differ")


if __name__ == "__main__":
    unittest.main()
