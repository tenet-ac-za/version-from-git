import importlib.util
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lookup_plugins"))

if importlib.util.find_spec("ansible") is None:
    ansible_module = types.ModuleType("ansible")
    errors_module = types.ModuleType("ansible.errors")
    errors_module.AnsibleError = RuntimeError
    plugins_module = types.ModuleType("ansible.plugins")
    lookup_module = types.ModuleType("ansible.plugins.lookup")
    lookup_module.LookupBase = type("LookupBase", (), {})
    sys.modules.update(
        {
            "ansible": ansible_module,
            "ansible.errors": errors_module,
            "ansible.plugins": plugins_module,
            "ansible.plugins.lookup": lookup_module,
        }
    )

from version_from_git import (
    AnsibleError,
    ConstraintError,
    STABILITIES,
    _resolve_terms,
    normalize_version,
    normalize_stability,
    parse_stability,
    satisfies,
    sort_versions,
)


class ComposerSemverTests(unittest.TestCase):
    def test_accepts_positional_term_or_target_option(self):
        self.assertEqual(_resolve_terms(["^1.2"], None), ["^1.2"])
        self.assertEqual(_resolve_terms([], "^1.2"), ["^1.2"])

    def test_rejects_missing_or_ambiguous_constraint(self):
        with self.assertRaises(AnsibleError):
            _resolve_terms([], None)
        with self.assertRaises(AnsibleError):
            _resolve_terms(["^1.2"], "^2.0")

    def test_normalizes_tags_and_branches(self):
        self.assertEqual(normalize_version("v1.2"), "1.2.0.0")
        self.assertEqual(normalize_version("1.2.3-RC1"), "1.2.3.0-RC1")
        self.assertEqual(normalize_version("dev-main"), "dev-main")
        self.assertEqual(normalize_version("1.x-dev"), "1.9999999.9999999.9999999-dev")

    def test_matches_composer_range_operators(self):
        self.assertTrue(satisfies("1.9.9", "^1.2"))
        self.assertFalse(satisfies("2.0.0", "^1.2"))
        self.assertTrue(satisfies("1.9.9", "~1.2"))
        self.assertFalse(satisfies("2.0.0", "~1.2"))
        self.assertTrue(satisfies("1.2.9", "~1.2.3"))
        self.assertFalse(satisfies("1.3.0", "~1.2.3"))
        self.assertTrue(satisfies("4.31.0", "~4.25"))
        self.assertFalse(satisfies("5.0.0", "~4.25"))
        self.assertTrue(satisfies("1.2.0-alpha1", ">=1"))
        self.assertFalse(satisfies("1.2.0-alpha1", "<1.2"))
        self.assertTrue(satisfies("1.4.2", ">=1.2 <2.0"))
        self.assertTrue(satisfies("1.4.2", "1.0 - 1.9"))
        self.assertFalse(satisfies("2.0.0", "1.0 - 1.9"))

    def test_wildcard_disjunction_and_stability(self):
        self.assertTrue(satisfies("1.4.2", "1.4.*"))
        self.assertTrue(satisfies("2.0.0", "1.* || 2.*"))
        self.assertTrue(satisfies("1.0.0-beta1", "^1.0@beta"))
        self.assertTrue(satisfies("dev-master", "master@dev"))
        self.assertEqual(parse_stability("1.0.0-beta2"), "beta")
        self.assertEqual(parse_stability("master@dev"), "dev")
        self.assertEqual(parse_stability("^1.0@beta"), "beta")
        self.assertEqual(parse_stability("dev-feature"), "dev")

    def test_stability_flags_match_supported_stabilities(self):
        for stability in STABILITIES:
            with self.subTest(stability=stability):
                self.assertEqual(
                    parse_stability("1.0@" + stability),
                    normalize_stability(stability),
                )

    def test_sorts_prereleases_before_stable_versions(self):
        self.assertEqual(
            sort_versions(
                ["1.0.0.0", "1.0.0.0-RC1", "1.0.0.0-beta1", "1.0.0.0-alpha1"]
            ),
            ["1.0.0.0-alpha1", "1.0.0.0-beta1", "1.0.0.0-RC1", "1.0.0.0"],
        )

    def test_rejects_invalid_versions_and_constraints(self):
        with self.assertRaises(ConstraintError):
            normalize_version("not-a-version")
        with self.assertRaises(ConstraintError):
            satisfies("1.0.0", "not a constraint")


if __name__ == "__main__":
    unittest.main()
