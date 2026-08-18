"""The front end, checked without a browser.

This file exists because of a specific afternoon. A button was added to the
header, its handler was wired to an id that didn't match the markup, and
because that throw happens at the top level of the script, *every* line after
it never ran. Send stopped working. The transcript stopped loading. The page
painted and then sat there, and none of it looked like a typo.

You cannot see any of that from Python — but you can check the two things that
cause it: that the ids the script reaches for exist in the markup, and that the
script parses at all.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "sevanya" / "web"
HTML = (WEB / "index.html").read_text()

SCRIPTS = re.findall(r"<script>(.*?)</script>", HTML, re.S)
MARKUP_IDS = set(re.findall(r'\bid="([^"]+)"', HTML))


def without_comments(script: str) -> str:
    """Strip JS comments before scanning for patterns.

    Needed because the comment on bind() quotes the very anti-pattern these
    tests look for, as an illustration. Scanning raw text flags the
    explanation as if it were the mistake.

    The line-comment rule skips '//' preceded by ':' so a URL in a string
    isn't mistaken for the start of a comment.
    """
    script = re.sub(r"/\*.*?\*/", "", script, flags=re.S)
    return re.sub(r"(?<!:)//[^\n]*", "", script)


CODE = [without_comments(s) for s in SCRIPTS]


def referenced_ids():
    """Every id the script asks the DOM for, however it asks."""
    found = set()
    for script in CODE:
        found |= set(re.findall(r"getElementById\(\s*'([^']+)'", script))
        found |= set(re.findall(r"\bbind\(\s*'([^']+)'", script))
    return found


def test_the_page_has_script_to_check():
    assert SCRIPTS, "no script blocks found — the regex or the page changed"
    assert MARKUP_IDS


@pytest.mark.parametrize("element_id", sorted(referenced_ids()))
def test_every_id_the_script_reaches_for_exists_in_the_markup(element_id):
    """The exact check that was missing.

    getElementById returns null for an id that isn't there, assigning .onclick
    on null throws, and at top level that throw takes the rest of the script
    with it.
    """
    assert element_id in MARKUP_IDS, (
        f"the script looks for #{element_id}, which is not in the markup. "
        f"ids present: {sorted(MARKUP_IDS)}"
    )


def test_buttons_are_wired_through_bind():
    """bind() reports a mismatch and keeps going; direct assignment doesn't.

    One wrong string in the direct form takes down every handler after it, so
    the whole page goes inert. Keep new buttons on bind().
    """
    offenders = []
    for script in CODE:
        for match in re.finditer(r"getElementById\(\s*'([^']+)'\s*\)\s*\.on\w+\s*=", script):
            offenders.append(match.group(1))
    assert not offenders, (
        f"wire these with bind(id, fn) instead of getElementById().onclick=: {offenders}"
    )


def test_the_error_reporter_is_installed_before_the_main_script():
    """It has to be its own earlier block to be any use.

    A syntax error is thrown while its own script is being compiled, so a
    handler declared inside that script never registered to catch it. And on a
    phone there is no console — if this block goes, a script death is silent
    and undebuggable from the device.
    """
    assert len(SCRIPTS) >= 2, "the error reporter's separate script block is gone"
    first = SCRIPTS[0]
    assert "addEventListener('error'" in first
    assert "unhandledrejection" in first
    assert "const " not in first.split("addEventListener")[0], (
        "the reporter must not depend on anything declared later"
    )


@pytest.mark.skipif(not shutil.which("node"), reason="node not available to parse JS")
@pytest.mark.parametrize("index", range(len(SCRIPTS)))
def test_each_script_block_parses(tmp_path, index):
    """A syntax error anywhere in a block kills that whole block."""
    js = tmp_path / f"block{index}.js"
    js.write_text(SCRIPTS[index])
    result = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
    assert result.returncode == 0, f"script block {index} does not parse:\n{result.stderr}"


# --- the manifest and what it promises -------------------------------------


def test_manifest_icons_exist_on_disk():
    """A declared icon that isn't there is a blurry screenshot on the home screen."""
    import json

    manifest = json.loads((WEB / "manifest.json").read_text())
    assert manifest["icons"], "no icons declared"
    for icon in manifest["icons"]:
        path = WEB / icon["src"].lstrip("/").replace("static/", "static/", 1)
        assert (WEB / "static" / Path(icon["src"]).name).exists(), f"{icon['src']} is declared but missing"


def test_apple_touch_icon_is_declared_and_present():
    """iOS ignores the manifest for the home screen icon and wants this link."""
    match = re.search(r'rel="apple-touch-icon"\s+href="([^"]+)"', HTML)
    assert match, "no apple-touch-icon — iOS will use a screenshot of the page"
    assert (WEB / "static" / Path(match.group(1)).name).exists()


def test_the_token_can_be_entered_on_the_device():
    """There is no JS console on an iPhone.

    If this ever regresses to "set localStorage from the console", the app is
    unusable on the device it exists for whenever a token is set.
    """
    assert "token-input" in MARKUP_IDS, "no way to type a token in the UI"
    assert "askToken" in HTML
    assert "searchParams.get('token')" in HTML, "no ?token= path for a Shortcut or QR code"
