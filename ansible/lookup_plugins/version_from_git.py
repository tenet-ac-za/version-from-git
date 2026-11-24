"""Find the latest Git ref matching a Composer-style version constraint."""

import os
import re
import shlex
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from functools import cmp_to_key
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

STABILITIES = ("dev", "alpha", "beta", "RC", "stable")
_STABILITY_INDEX = {name.lower(): index for index, name in enumerate(STABILITIES)}
_STABILITY_FLAG_RE = re.compile(
    r"@(" + "|".join(re.escape(name) for name in STABILITIES) + r")$",
    re.IGNORECASE,
)
_COMPARATOR_HAS_MODIFIER = re.compile(
    r"-(?:stable|beta|b|rc|alpha|a|patch|pl|p)(?:[.-]?\d+)*(?:[.-]?dev)?$"
    r"|[.-]dev$",
    re.IGNORECASE,
)
_VERSION = re.compile(
    r"^v?(\d{1,5})(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?"
    r"([._-]?(?:(stable|beta|b|rc|alpha|a|patch|pl|p)((?:[.-]?\d+)*)?)?)?"
    r"([.-]?dev)?$",
    re.IGNORECASE,
)
_BRANCH_VERSION = re.compile(
    r"^v?(\d+)(?:\.(\d+|[xX*]))?(?:\.(\d+|[xX*]))?(?:\.(\d+|[xX*]))?$",
    re.IGNORECASE,
)
_DATE_VERSION = re.compile(
    r"^v?(\d{4}(?:[.:-]?\d{2}){1,6}(?:[.:-]?\d{1,3}){0,2})"
    r"([._-]?(?:(stable|beta|b|rc|alpha|a|patch|pl|p)((?:[.-]?\d+)*)?)?)?"
    r"([.-]?dev)?$",
    re.IGNORECASE,
)
_ATOM_RE = re.compile(r"(?:>=|<=|<>|!=|==|>|<|=)\s*[^\s,]+|[^\s,]+")
_PRE_RELEASE = re.compile(r"^(dev|alpha|beta|rc|patch)(\d*)$", re.IGNORECASE)


class ConstraintError(ValueError):
    """Raised when a version or Composer constraint cannot be parsed."""


def normalize_stability(stability: str) -> str:
    normalized = stability.lower()
    if normalized not in _STABILITY_INDEX:
        expected = ", ".join(STABILITIES[:-1]) + " or " + STABILITIES[-1]
        raise ConstraintError(
            "Invalid stability {!r}; expected one of {}".format(stability, expected)
        )
    return "RC" if normalized == "rc" else normalized


def parse_stability(version: str) -> str:
    version = version.split("#", 1)[0]
    stability_flag = _STABILITY_FLAG_RE.search(version)
    if stability_flag:
        return normalize_stability(stability_flag.group(1))
    if version.lower().startswith("dev-") or version.lower().endswith("-dev"):
        return "dev"
    match = re.search(
        r"[._-]?(stable|beta|b|rc|alpha|a|patch|pl|p)(?:[.-]?\d+)*(?:\+.*)?$",
        version,
        re.IGNORECASE,
    )
    if not match:
        return "stable"
    name = match.group(1).lower()
    if name in ("beta", "b"):
        return "beta"
    if name in ("alpha", "a"):
        return "alpha"
    if name == "rc":
        return "RC"
    return "stable"


def normalize_version(version: str) -> str:
    original = version
    version = version.strip()
    alias = re.match(r"^([^,\s]+)\s+as\s+([^,\s]+)$", version)
    if alias:
        version = alias.group(1)
    version = _STABILITY_FLAG_RE.sub("", version)

    if version in ("master", "trunk", "default"):
        version = "dev-" + version
    if version.lower().startswith("dev-"):
        return "dev-" + version[4:]

    build = re.match(r"^([^,\s+]+)\+[^\s]+$", version)
    if build:
        version = build.group(1)

    match = _VERSION.match(version)
    if match:
        parts = [match.group(i) or "0" for i in range(1, 5)]
        normalized = ".".join(parts)
        modifier = match.group(6)
        if modifier:
            name = modifier.lower()
            name = {
                "a": "alpha",
                "b": "beta",
                "p": "patch",
                "pl": "patch",
                "rc": "RC",
            }.get(name, name)
            suffix = (match.group(7) or "").lstrip(".-")
            if name != "stable":
                normalized += "-" + name + suffix
        if match.group(8):
            normalized += "-dev"
        return normalized

    date_match = _DATE_VERSION.match(version)
    if date_match:
        normalized = re.sub(r"\D", ".", date_match.group(1))
        modifier = date_match.group(3)
        if modifier:
            name = modifier.lower()
            name = {
                "a": "alpha",
                "b": "beta",
                "p": "patch",
                "pl": "patch",
                "rc": "RC",
            }.get(name, name)
            suffix = (date_match.group(4) or "").lstrip(".-")
            if name != "stable":
                normalized += "-" + name + suffix
        if date_match.group(5):
            normalized += "-dev"
        return normalized

    branch_match = re.match(r"^(.*?)[.-]?dev$", version, re.IGNORECASE)
    if branch_match:
        branch = branch_match.group(1)
        numeric_branch = _normalize_branch(branch)
        if not numeric_branch.startswith("dev-"):
            return numeric_branch

    raise ConstraintError("Invalid version string {!r}".format(original))


def _normalize_branch(name: str) -> str:
    match = _BRANCH_VERSION.match(name.strip())
    if not match:
        return "dev-" + name.strip()
    parts = []
    for index in range(1, 5):
        part = match.group(index)
        if part is None:
            part = "x"
        parts.append("9999999" if part.lower() in ("x", "*") else part)
    return ".".join(parts) + "-dev"


def compare_versions(left: str, right: str) -> int:
    if left == right:
        return 0
    left_branch = left.startswith("dev-")
    right_branch = right.startswith("dev-")
    if left_branch or right_branch:
        return 0

    left_parts, left_pre = _split_version(left)
    right_parts, right_pre = _split_version(right)
    length = max(len(left_parts), len(right_parts))
    left_parts += (0,) * (length - len(left_parts))
    right_parts += (0,) * (length - len(right_parts))
    if left_parts != right_parts:
        return -1 if left_parts < right_parts else 1

    ranks = {"dev": 0, "alpha": 1, "beta": 2, "rc": 3, "stable": 4, "patch": 5}
    left_rank, left_number = _pre_rank(left_pre, ranks)
    right_rank, right_number = _pre_rank(right_pre, ranks)
    if left_rank != right_rank:
        return -1 if left_rank < right_rank else 1
    if left_number != right_number:
        return -1 if left_number < right_number else 1
    return 0


def sort_versions(versions: Sequence[str]) -> List[str]:
    def sort_key(version: str) -> str:
        if version in ("dev-master", "dev-default", "dev-trunk"):
            return "9999999-dev"
        return version

    return sorted(
        versions,
        key=cmp_to_key(lambda left, right: compare_versions(sort_key(left), sort_key(right))),
    )


def satisfies(version: str, constraint: str) -> bool:
    candidate = normalize_version(version)
    groups = _parse_constraint(constraint)
    return any(
        all(_matches(candidate, operator, boundary) for operator, boundary in group)
        for group in groups
    )


def _split_version(version: str) -> Tuple[Tuple[int, ...], str]:
    parts, separator, suffix = version.partition("-")
    try:
        numbers = tuple(int(part) for part in parts.split("."))
    except ValueError as exc:
        raise ConstraintError("Invalid normalized version {!r}".format(version)) from exc
    return numbers, suffix if separator else ""


def _pre_rank(suffix: str, ranks: Dict[str, int]) -> Tuple[int, int]:
    match = _PRE_RELEASE.match(suffix)
    if not match:
        return ranks["stable"], 0
    return ranks[match.group(1).lower()], int(match.group(2) or 0)


def _parse_constraint(constraint: str) -> List[List[Tuple[str, str]]]:
    if not constraint.strip():
        raise ConstraintError("Constraint must not be empty")

    groups: List[List[Tuple[str, str]]] = []
    for raw_group in re.split(r"\s*\|\|?\s*", constraint.strip()):
        raw_group = re.sub(r"\s+as\s+\S+$", "", raw_group)
        if not raw_group:
            raise ConstraintError("Invalid empty alternative in constraint")

        hyphen = re.match(r"^(.+?)\s+-\s+(.+)$", raw_group)
        if hyphen:
            groups.append(_hyphen_range(hyphen.group(1), hyphen.group(2)))
            continue

        atoms = _ATOM_RE.findall(raw_group)
        if not atoms:
            raise ConstraintError("Could not parse version constraint {!r}".format(raw_group))
        group: List[Tuple[str, str]] = []
        for atom in atoms:
            group.extend(_parse_atom(atom))
        groups.append(group)
    return groups


def _version_parts(version: str) -> Tuple[List[int], bool]:
    version = re.sub(r"\+[^\s]+$", "", version)
    match = _VERSION.match(version)
    if not match:
        raise ConstraintError("Could not parse version constraint {!r}".format(version))
    parts = [int(match.group(i) or 0) for i in range(1, 5)]
    explicit = bool(match.group(5) and match.group(6))
    return parts, explicit


def _increment(parts: Sequence[int], position: int) -> str:
    result = list(parts[:4])
    result.extend([0] * (4 - len(result)))
    result[position - 1] += 1
    for index in range(position, 4):
        result[index] = 0
    return ".".join(str(part) for part in result)


def _range_parts(
    low: str, high: str, low_operator: str = ">=", high_operator: str = "<"
) -> List[Tuple[str, str]]:
    return [(low_operator, low), (high_operator, high)]


def _parse_atom(atom: str) -> List[Tuple[str, str]]:
    atom = re.sub(r"#.+$", "", atom)
    stability = None
    flag = _STABILITY_FLAG_RE.search(atom)
    if flag:
        flagged_stability = normalize_stability(flag.group(1))
        if flagged_stability != "stable":
            stability = flagged_stability
        atom = atom[: flag.start()] or "*"

    if re.match(r"^[xX*](?:\.[xX*])*$", atom):
        return []

    wildcard = re.match(
        r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.[xX*])+$", atom, re.IGNORECASE
    )
    if wildcard:
        found = [wildcard.group(i) for i in range(1, 4)]
        position = max(index for index, part in enumerate(found, 1) if part is not None)
        parts = [int(part or 0) for part in found] + [0]
        low = ".".join(str(part) for part in parts) + "-dev"
        high = _increment(parts, position) + "-dev"
        if low == "0.0.0.0-dev":
            return [("<", high)]
        return _range_parts(low, high)

    tilde_or_caret = re.match(r"^(~|\^)(.+)$", atom)
    if tilde_or_caret:
        operator, version = tilde_or_caret.groups()
        parts, explicit = _version_parts(version)
        if operator == "~":
            count = len(
                re.match(r"^v?\d+(?:\.\d+){0,3}", version)
                .group(0)
                .lstrip("vV")
                .split(".")
            )
            position = min(count, 4)
        elif parts[0] != 0 or len(version.split(".", 1)) == 1:
            position = 1
        elif parts[1] != 0:
            position = 2
        else:
            position = 3
        low = normalize_version(version if explicit else version + "-dev")
        high_position = max(1, position - 1) if operator == "~" else position
        return _range_parts(low, _increment(parts, high_position) + "-dev")

    comparator = re.match(r"^(<>|!=|>=|<=|==|>|<|=)?\s*(.*?)$", atom)
    if not comparator or not comparator.group(2):
        raise ConstraintError("Could not parse version constraint {!r}".format(atom))
    operator = comparator.group(1) or "="
    value = comparator.group(2)
    value = re.sub(r"^(dev-[^,\s@]+?|[^,\s@]+?\.x-dev)#.+$", r"\1", value, flags=re.IGNORECASE)
    try:
        normalized = normalize_version(value)
    except ConstraintError:
        if value.lower().endswith("-dev") and re.match(r"^[0-9a-zA-Z-./]+$", value):
            normalized = normalize_version("dev-" + value[:-4])
        else:
            raise

    if operator not in ("==", "=") and stability and parse_stability(normalized) == "stable":
        normalized += "-" + stability
    elif operator in ("<", ">=") and not _COMPARATOR_HAS_MODIFIER.search(value):
        if not value.lower().startswith("dev-"):
            normalized += "-dev"
    return [(operator, normalized)]


def _hyphen_range(low_value: str, high_value: str) -> List[Tuple[str, str]]:
    _, low_explicit = _version_parts(low_value)
    high_parts, high_explicit = _version_parts(high_value)
    low = normalize_version(low_value)
    if not low_explicit and not low.endswith("-dev"):
        low += "-dev"

    high_count = len(
        re.match(r"^v?\d+(?:\.\d+){0,3}", high_value)
        .group(0)
        .lstrip("vV")
        .split(".")
    )
    if high_count >= 3 or high_explicit:
        high = normalize_version(high_value)
        return _range_parts(low, high, ">=", "<=")
    return _range_parts(low, _increment(high_parts, high_count) + "-dev")


def _matches(candidate: str, operator: str, boundary: str) -> bool:
    if candidate.startswith("dev-") or boundary.startswith("dev-"):
        if operator in ("=", "=="):
            return candidate == boundary
        if operator in ("!=", "<>"):
            return candidate != boundary
        return False

    comparison = compare_versions(candidate, boundary)
    return {
        "=": comparison == 0,
        "==": comparison == 0,
        "!=": comparison != 0,
        "<>": comparison != 0,
        ">": comparison > 0,
        ">=": comparison >= 0,
        "<": comparison < 0,
        "<=": comparison <= 0,
    }[operator]


DOCUMENTATION = r"""
name: version_from_git
author: Guy Halse
version_added: "1.0.0"
short_description: Find the latest Git ref matching a Composer-style constraint
description:
  - Reads tags and branches from a local or remote Git repository.
  - Selects the highest matching version using Composer-compatible constraints.
options:
  _terms:
    description: Composer-style version constraint.
    type: list
    elements: string
  constraint:
    description: Composer-style version constraint, as an alternative to a positional term.
    type: string
  repo:
    description: Local repository path or remote Git URL.
    type: string
    default: "."
  sshkey:
    description: SSH private key path for remote Git access. Relative paths use Ansible's task search path.
    type: string
    secret: true
  sshkey_temp_copy_unsafe:
    description: Copy sshkey to a private temporary file if its permissions are too broad.
    type: boolean
    default: false
  stability:
    description: Require exactly this stability (dev, alpha, beta, RC, or stable).
    type: string
  git:
    description: Git executable path. Defaults to GITCMD or git.
    type: string
  output:
    description: Result to return for each constraint.
    type: string
    choices: [refspec, ref, refname, commit, composer, text, json]
    default: refspec
  verbose:
    description: Log repository and matching-version details at Ansible verbosity level 3.
    type: boolean
    default: false
"""

EXAMPLES = r"""
- name: Find a matching release ref
  ansible.builtin.debug:
    msg: "{{ query('version_from_git', '^1.2', repo='/srv/project', output='json')[0].latest }}"

- name: Find a matching release using the constraint option
  ansible.builtin.debug:
    msg: "{{ query('version_from_git', constraint='^1.2', repo='/srv/project')[0] }}"

- name: Use a private temporary copy of a key from a filesystem with broad permissions
  ansible.builtin.debug:
    msg: "{{ query('version_from_git', '^1.2', repo='git@example.com:project.git', sshkey='keys/deploy', sshkey_temp_copy_unsafe=true)[0] }}"
"""

RETURN = r"""
_list:
  description: One result for each supplied version constraint.
  type: list
  elements: raw
"""


class LookupModule(LookupBase):
    def run(
        self,
        terms: List[str],
        variables: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> List[Any]:
        self.set_options(var_options=variables, direct=kwargs)
        terms = _resolve_terms(terms, self.get_option("constraint"))
        repo = self.get_option("repo")
        sshkey = self._resolve_sshkey(self.get_option("sshkey"), variables)
        sshkey_temp_copy_unsafe = self.get_option("sshkey_temp_copy_unsafe")
        git = self.get_option("git") or os.environ.get("GITCMD") or "git"
        output = self.get_option("output")
        stability = self.get_option("stability")
        verbose = self.get_option("verbose")

        if stability is not None:
            try:
                stability = normalize_stability(stability)
            except ConstraintError as exc:
                raise AnsibleError(str(exc)) from exc

        versions = self._get_versions(
            repo, sshkey, git, verbose, sshkey_temp_copy_unsafe
        )
        results = []
        for constraint in terms:
            try:
                matching = [
                    version for version in versions if satisfies(version, str(constraint))
                ]
            except ConstraintError as exc:
                raise AnsibleError(
                    "Invalid version constraint {!r}: {}".format(constraint, exc)
                ) from exc

            if not matching:
                raise AnsibleError(
                    "No versions match the constraint: {}".format(constraint)
                )

            desired_stability = stability or parse_stability(str(constraint))
            matching = [
                version
                for version in matching
                if (
                    parse_stability(version) == desired_stability
                    if stability is not None
                    else _stability_rank(parse_stability(version))
                    >= _stability_rank(desired_stability)
                )
            ]
            if not matching:
                raise AnsibleError(
                    "No versions matching {!r} satisfy the stability constraint: {}".format(
                        constraint, desired_stability
                    )
                )

            matching = sort_versions(matching)
            latest = matching[-1]
            if verbose:
                self._display.vvv(
                    "Matching versions for {!r}: {}".format(constraint, ", ".join(matching))
                )
            results.append(_format_result(output, latest, matching, versions))
        return results

    def _resolve_sshkey(
        self, sshkey: Optional[str], variables: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        if sshkey is None:
            return None

        path = self.find_file_in_search_path(
            variables or {}, "files", sshkey, ignore_missing=True
        )
        if path is None:
            raise AnsibleError(
                "Could not find SSH key {!r} in Ansible's task search path".format(
                    sshkey
                )
            )
        return path

    def _get_versions(
        self,
        repo: str,
        sshkey: Optional[str],
        git: str,
        verbose: bool,
        sshkey_temp_copy_unsafe: bool = False,
    ) -> Dict[str, Dict[str, str]]:
        if os.path.isdir(repo):
            command = [git, "-C", repo, "show-ref", "--tags", "--heads"]
            process = self._run_git(command, verbose)
        else:
            with _sshkey_for_git(
                sshkey, sshkey_temp_copy_unsafe, self._display.warning
            ) as git_sshkey:
                command = [git]
                if git_sshkey:
                    command.extend(
                        [
                            "-c",
                            "core.sshCommand=ssh -i {} -o StrictHostKeyChecking=accept-new".format(
                                shlex.quote(git_sshkey)
                            ),
                        ]
                    )
                command.extend(["ls-remote", "-q", "--heads", "--tags", repo])
                process = self._run_git(command, verbose)

        if process.returncode:
            detail = process.stderr.strip()
            message = "Failed to get versions from Git repository"
            if detail:
                message += ": " + detail
            raise AnsibleError(message)

        versions: Dict[str, Dict[str, str]] = {}
        for line in process.stdout.splitlines():
            fields = line.split(None, 1)
            if len(fields) != 2:
                continue
            commit, refspec = fields
            if refspec.startswith("refs/heads/"):
                name = refspec[len("refs/heads/") :]
                source_version = name + "-dev" if name[:1].isdigit() else "dev-" + name
            elif refspec.startswith("refs/tags/"):
                source_version = refspec[len("refs/tags/") :]
            else:
                continue

            try:
                version = normalize_version(source_version)
            except ConstraintError:
                continue
            versions[version] = {
                "refspec": refspec,
                "commit": commit,
            }
        return versions

    def _run_git(self, command: List[str], verbose: bool) -> subprocess.CompletedProcess:
        if verbose:
            self._display.vvv(
                "Executing Git command: {}".format(
                    " ".join(shlex.quote(part) for part in command)
                )
            )
        try:
            process = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise AnsibleError("Could not execute Git: {}".format(exc)) from exc
        return process


def _resolve_terms(terms: List[str], constraint: Optional[str]) -> List[str]:
    if terms and constraint is not None:
        raise AnsibleError(
            "Specify the version constraint as either a positional term or constraint, not both"
        )
    if constraint is not None:
        return [constraint]
    if not terms:
        raise AnsibleError("A version constraint must be specified as a positional term or constraint")
    return terms


@contextmanager
def _sshkey_for_git(
    sshkey: Optional[str],
    copy_to_temp: bool,
    warning: Callable[[str], None],
) -> Iterator[Optional[str]]:
    if sshkey is None:
        yield sshkey
        return

    if os.name == "posix":
        try:
            source_stat = os.stat(sshkey)
        except OSError as exc:
            raise AnsibleError(
                "Could not inspect SSH key {!r}: {}".format(sshkey, exc)
            ) from exc
        if (
            source_stat.st_uid == os.getuid()
            and source_stat.st_mode & 0o400
            and not source_stat.st_mode & 0o077
        ):
            yield sshkey
            return
        if not copy_to_temp:
            warning(
                "SSH key {!r} may have insecure permissions; if your filesystem "
                "does not enforce private permissions, set "
                "sshkey_temp_copy_unsafe to true to copy it to a private "
                "temporary file".format(sshkey)
            )
            yield sshkey
            return
    elif not copy_to_temp:
        yield sshkey
        return

    with tempfile.TemporaryDirectory(prefix="version-from-git-") as temp_dir:
        temp_key = os.path.join(temp_dir, "sshkey")
        try:
            os.umask(0o077)
            with open(sshkey, "rb") as source, open(temp_key, "xb") as destination:
                shutil.copyfileobj(source, destination)
            os.chmod(temp_key, 0o600)
            if os.name == "posix":
                for path in (temp_dir, temp_key):
                    if os.stat(path).st_mode & 0o077:
                        raise AnsibleError(
                            "Temporary filesystem does not enforce private permissions; "
                            "set TMPDIR to a filesystem that supports them"
                        )
        except OSError as exc:
            raise AnsibleError(
                "Could not create a private temporary copy of SSH key {!r}: {}".format(
                    sshkey, exc
                )
            ) from exc
        yield temp_key


def _stability_rank(stability: str) -> int:
    return _STABILITY_INDEX[stability.lower()]


def _version_info(version: str, versions: Dict[str, Dict[str, str]]) -> Dict[str, str]:
    entry = versions[version]
    refspec = entry["refspec"]
    refname = refspec
    for prefix in ("refs/heads/", "refs/tags/"):
        if refname.startswith(prefix):
            refname = refname[len(prefix) :]
            break
    return {
        "version": version,
        "refspec": refspec,
        "refname": refname,
        "reftype": "tag" if refspec.startswith("refs/tags/") else "branch",
        "commit": entry["commit"],
    }


def _format_result(
    output: str,
    latest: str,
    matching: List[str],
    versions: Dict[str, Dict[str, str]],
) -> Any:
    latest_info = _version_info(latest, versions)
    if output in ("ref", "refspec"):
        return latest_info["refspec"]
    if output == "refname":
        return latest_info["refname"]
    if output == "commit":
        return latest_info["commit"]
    if output == "composer":
        return latest_info["version"]
    if output == "text":
        return "\n".join(
            "{}: {}".format(key, value) for key, value in latest_info.items()
        )
    if output == "json":
        return {
            "latest": latest_info,
            "matching": [_version_info(version, versions) for version in matching],
        }
    raise AnsibleError("Invalid output format: {}".format(output))
