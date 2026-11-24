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

The constraint can also be supplied by name instead of positionally: `query('version_from_git', target='^1.2', repo='...')`. Specify either positional terms or `target`, not both.

Supported options correspond to the existing command, with `target` as an alternative to the positional constraint: `repo`, `sshkey`, `stability`, `git`, `output`, and `verbose`. `output` accepts `refspec` (default), `ref`, `refname`, `commit`, `composer`, `text`, or `json`. The `json` result is a native mapping, not a JSON-encoded string. Lookup failures raise `AnsibleError`.

The constraint matcher supports Composer-style exact versions, comparisons, `!=`, AND/OR ranges, hyphen ranges, wildcards, tilde and caret ranges, and stability flags. As in the original command, an optional `stability` selects exactly one stability; otherwise the constraint's stability sets the minimum allowed level (stable by default).

Run the focused matcher tests with:

```sh
python -m unittest discover -s ansible/tests
```
