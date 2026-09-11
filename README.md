# version-from-git

This finds the latest version of software from a Git repository, by matching tags or branches against a given version constraint. The idea is it can be used as a helper when installing software, to make sure we always find the right version to install.

## Usage

`version-from-git.phar [--repo=<repo>] [--sshkey=<ssh_key>] <constraint[@stability]>`

## Versions and constraints

`version-from-git` uses Composer's [semmvar](https://github.com/composer/semver) to process constraint strings, meaning that you can specify versions and constraints exactly as you would with Composer. See the [versions and constraints](https://getcomposer.org/doc/articles/versions.md) documentation in Composer.

The default minimum stability is `stable`, which can be changed by appending a stability to the constraint string (e.g. `@dev`) as described in the Composer documentation.

## Options

: `--repo=<repo>`, `-r <repo>`
Specify the repository to query. This can either be a local repository given by filesystem path, or a remote repository given by URL. Defaults to the current directory.

Examples:
* `--repo=/path/to/my/local/repo` for a local repository
* `--repo=git@github.com:tenet-ac-za/version-from-git.git` for a remote repository on Github

: `--sshkey=<key>`, `-k <key>`
Where SSH is used as a transport, specify a SSH private key to use. This is useful where, for example, Github deploy keys have been used.

: `--stability=<stability>`, `-s <stability>`
Set the required stability. Must be one of: 'dev', 'alpha', 'beta', 'RC', 'stable'. Note this differs from a constraint in that the stability must match exactly.

: `--git=<cmd>`, `-g <cmd>`
Specify location of the git command (can also use the GITCMD enviroment variable)

: `--verbose`, `-v`
Print additional debugging output

: `--help`, `-h`, `-?`
Print usage information
