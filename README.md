# version-from-git

This finds the latest version of software from a Git repository, by matching tags or branches against a given version constraint. The idea is it can be used as a helper when installing software, to make sure we always find the right version to install.

## Usage

`version-from-git.phar [--repo=<repo>] [--sshkey=<ssh_key>] <constraint[@stability]>`

## Versions and constraints

`version-from-git` uses Composer's [semmvar](https://github.com/composer/semver) to process constraint strings, meaning that you can specify versions and constraints exactly as you would with Composer. See the [versions and constraints](https://getcomposer.org/doc/articles/versions.md) documentation in Composer.

Note that individual commit hashes are not handled. Only branches and tags.

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

: `--output=<format>`, `-o <format>`
Specify the output format. See below for the available options.

: `--git=<cmd>`, `-g <cmd>`
Specify location of the git command (can also use the GITCMD enviroment variable)

: `--verbose`, `-v`
Print additional debugging output to stdout. The formatting of this output is not guarenteed, and may interfere with the parsing of output.

: `--help`, `-h`, `-?`
Print usage information

## Output Formats

The following output formats are available. Formats are mutually exclusive, and unless otherwise specified produce a single line of output for a valid version or an empty line where no valid version could be found (an error message may be printed on stderr).

: `refspec`
Print the git refspec (e.g. `refs/heads/main` or `refs/tags/v1.0.0`).

: `refname`
Print the git reference name (e.g. `main` or `v1.0.0`).

: `commit`
Print the git commit hash (e.g. `b40592d66bf37c9fe7bb2a83c58456761a70eb51`)

: `composer`
Print the normalised composer form of the version number (e.g. `1.0.0.0`, `1.1.0.0-RC3`)

: `text`
Prints a colon separated list of key/values, one per line. For example:
```text
version: 1.0.0.0
refspec: refs/tags/v1.0.0
refname: v1.0.0
reftype: tag
commit: b40592d66bf37c9fe7bb2a83c58456761a70eb51
```
The order of keys is not guarenteed.

: `json`
Prints a JSON object containing both the latest version as well as all matching versions. For example:
```json
{
    "latest": {
        "version": "1.0.0.0",
        "refspec": "refs\/tags\/v1.0.0",
        "refname": "v1.0.0",
        "reftype": "tag",
        "commit": "b40592d66bf37c9fe7bb2a83c58456761a70eb51"
    },
    "matching": [
        {
            "version": "0.1.0.0",
            "refspec": "refs\/tags\/v0.1.0",
            "refname": "v0.1.0",
            "reftype": "tag",
            "commit": "2a9801a35db0421720f3b534b8b29814ab3ea9c9"
        },
        {
            "version": "1.0.0.0",
            "refspec": "refs\/tags\/v1.0.0",
            "refname": "v1.0.0",
            "reftype": "tag",
            "commit": "b40592d66bf37c9fe7bb2a83c58456761a70eb51"
        }
    ]
}
```
Will return valid, but empty JSON on error.

## Exit codes

 0 = success: A version was found.

 1 = failure: No compatible version could be found.

 2 = error: some error condition occured, and the results are inconclusive.

