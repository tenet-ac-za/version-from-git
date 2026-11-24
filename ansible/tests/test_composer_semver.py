import importlib.util
import os
import sys
import tempfile
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
    LookupModule,
    STABILITIES,
    _resolve_terms,
    _sshkey_for_git,
    normalize_version,
    normalize_stability,
    parse_stability,
    satisfies,
    sort_versions,
)


class ComposerSemverTests(unittest.TestCase):
    def test_sshkey_temporary_copy_is_opt_in_private_and_cleaned_up(self):
        with tempfile.TemporaryDirectory() as source_dir:
            source_key = os.path.join(source_dir, "key")
            with open(source_key, "wb") as key_file:
                key_file.write(b"private-key-data")
            if os.name == "posix":
                os.chmod(source_key, 0o644)

            warnings = []
            with _sshkey_for_git(source_key, False, warnings.append) as unchanged_key:
                self.assertEqual(unchanged_key, source_key)
            if os.name == "posix":
                self.assertEqual(len(warnings), 1)
                self.assertIn("sshkey_temp_copy_unsafe", warnings[0])

            with _sshkey_for_git(source_key, True, warnings.append) as copied_key:
                self.assertNotEqual(copied_key, source_key)
                with open(copied_key, "rb") as key_file:
                    self.assertEqual(key_file.read(), b"private-key-data")
                if os.name == "posix":
                    self.assertEqual(os.stat(copied_key).st_mode & 0o777, 0o600)
                    self.assertEqual(
                        os.stat(os.path.dirname(copied_key)).st_mode & 0o777,
                        0o700,
                    )

            self.assertFalse(os.path.exists(copied_key))

    @unittest.skipUnless(os.name == "posix", "POSIX permission bits are required")
    def test_sshkey_temporary_copy_reuses_private_key(self):
        with tempfile.TemporaryDirectory() as source_dir:
            source_key = os.path.join(source_dir, "key")
            with open(source_key, "wb") as key_file:
                key_file.write(b"private-key-data")
            os.chmod(source_key, 0o600)

            warnings = []
            with _sshkey_for_git(source_key, True, warnings.append) as selected_key:
                self.assertEqual(selected_key, source_key)
            self.assertEqual(warnings, [])

    def test_resolves_sshkey_through_ansible_task_search_path(self):
        variables = {"playbook_dir": os.path.abspath("playbooks")}

        class SearchPathLookup:
            def find_file_in_search_path(
                self, search_variables, subdir, path, ignore_missing=False
            ):
                self.call = (search_variables, subdir, path, ignore_missing)
                return os.path.join(search_variables["playbook_dir"], "files", path)

        lookup = SearchPathLookup()
        self.assertEqual(
            LookupModule._resolve_sshkey(lookup, "keys/deploy", variables),
            os.path.join(variables["playbook_dir"], "files", "keys/deploy"),
        )
        self.assertEqual(lookup.call, (variables, "files", "keys/deploy", True))

    def test_rejects_sshkey_not_found_in_ansible_search_path(self):
        class SearchPathLookup:
            def find_file_in_search_path(self, *args, **kwargs):
                return None

        with self.assertRaises(AnsibleError):
            LookupModule._resolve_sshkey(SearchPathLookup(), "deploy-key", {})

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
