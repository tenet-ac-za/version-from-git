# Ansible lookup plugin

`lookup_plugins/version_from_git.py` is a single-file control-node lookup for selecting the latest matching Git tag or branch using Composer-style version constraints. Its matcher uses Python's standard library and does not require the PHP Composer package or a third-party Python semver library.

Add the plugin directory to the playbook's lookup path:

```ini
[defaults]
lookup_plugins = ./ansible/lookup_plugins
```

Use `query()` to preserve Ansible's list-of-results convention. Each positional term is resolved separately:

```yaml
- hosts: localhost
  gather_facts: false
  tasks:
    - name: Find the latest stable release
      ansible.builtin.debug:
        msg: "{{ release[0].latest }}"
      vars:
        release: >-
          {{ query(
               'version_from_git',
               '^1.2',
               repo='https://example.com/project.git',
               output='json'
             ) }}
```

The constraint can also be supplied by name instead of positionally: `query('version_from_git', constraint='^1.2', repo='...')`. Specify either positional terms or `constraint`, not both.

Supported options correspond to the existing command, with `constraint` as an alternative to the positional constraint: `repo`, `sshkey`, `sshkey_temp_copy_unsafe`, `stability`, `git`, `output`, and `verbose`. Relative `sshkey` paths use Ansible's standard task search path: role and task paths are checked before the playbook directory. By default, the key is used in place; on POSIX, an insecure permission mode triggers a warning. Set `sshkey_temp_copy_unsafe=true` to copy a key that is not owned by the current user with user-read permission and no group/other permissions into a private temporary directory with mode `0600`. An already-private POSIX key is used directly. The temporary copy is removed after Git exits, and the source key is unchanged. On POSIX, the plugin verifies the temp filesystem honors private permissions; if not, set `TMPDIR` to a suitable local filesystem. `output` accepts `refspec` (default), `ref`, `refname`, `commit`, `composer`, `text`, or `json`. The `json` result is a native mapping, not a JSON-encoded string. Lookup failures raise `AnsibleError`.

The constraint matcher supports Composer-style exact versions, comparisons, `!=`, AND/OR ranges, hyphen ranges, wildcards, tilde and caret ranges, and stability flags. As in the original command, an optional `stability` selects exactly one stability; otherwise the constraint's stability sets the minimum allowed level (stable by default).

Run the focused matcher tests with:

```sh
python -m unittest discover -s ansible/tests
```
