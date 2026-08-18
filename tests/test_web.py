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


# Ids the script creates rather than finds — `field.id = 'token-input'`. They
# can't be "missing from the markup" because the markup never mentions them,
# but they still have to be accounted for or the check below is just wrong.
BUILT_IN_JS = set(re.findall(r"\.id\s*=\s*'([^']+)'", HTML))


def test_the_page_has_script_to_check():
    assert SCRIPTS, "no script blocks found — the regex or the page changed"
    assert MARKUP_IDS


@pytest.mark.parametrize("element_id", sorted(referenced_ids()))
def test_every_id_the_script_reaches_for_exists_in_the_markup(element_id):
    """The exact check that was missing once.

    getElementById returns null for an id that isn't there, assigning .onclick
    on null throws, and at top level that throw takes the rest of the script
    with it.
    """
    assert element_id in MARKUP_IDS | BUILT_IN_JS, (
        f"the script looks for #{element_id}, which is neither in the markup "
        f"nor created in JS. ids present: {sorted(MARKUP_IDS)}"
    )


def test_buttons_are_wired_through_bind():
    """bind() reports a mismatch and keeps going; direct assignment doesn't.

    One wrong string in the direct form takes down every handler after it, so
    the whole page goes inert. Elements built in JS are exempt — they can't be
    missing from markup that doesn't mention them.
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


# --- the panel: one component, Back top-left, no Close ---------------------


def test_there_is_one_panel_not_a_stack_of_sheets():
    """Opening a second thing closes the first, so there's never a pile of
    overlays to dismiss one at a time."""
    assert 'id="panel"' in HTML
    assert HTML.count('id="panel"') == 1
    assert "function closePanel" in HTML


def test_the_way_out_is_back_in_the_header_not_a_close_at_the_bottom():
    """Close sat at the end of a long list, so on a phone you had to scroll to
    the bottom of everything to get out of it."""
    assert "‹ Back" in HTML
    # Both spellings: one in the markup, and one built in JS — the second is
    # how it would actually creep back, since the panel is assembled in code.
    assert ">Close<" not in HTML, "a Close button came back in the markup"
    assert not re.search(r"textContent\s*=\s*['\"]Close['\"]", HTML), (
        "a Close button is being built in JS"
    )
    head = HTML.split("function head(")[1].split("function body(")[0]
    assert "back.onclick = closePanel" in head


def test_the_panel_header_stays_put_while_the_list_scrolls():
    header = HTML.split("#panel .head {")[1].split("}")[0]
    assert "position:sticky" in header
    assert "top:0" in header


def test_back_only_appears_where_the_panel_covers_the_screen():
    """On desktop the button that opened it is still visible behind and
    toggles it shut, so Back would be a second way to do one thing."""
    assert "#panel .head .back { display:none;" in HTML
    narrow = HTML.split("@media (max-width: 640px)")[1]
    assert "#panel .head .back { display:inline-block; }" in narrow
    assert "height:100dvh" in narrow, "the panel should cover the screen on a phone"


def test_the_same_button_closes_the_panel_it_opened():
    """Only reachable on desktop, where the header isn't covered — but that's
    where a dropdown that won't shut is most annoying."""
    show = HTML.split("async function show(")[1].split("function replace(")[0]
    assert "if (openName === name) { closePanel(); return; }" in show


def test_clicking_away_is_judged_before_the_panel_can_be_rebuilt():
    """Capture phase, and it matters.

    A row whose handler rebuilds the panel is detached by the time a bubbled
    listener runs, so panel.contains(target) is false and the handler closes
    the panel that row had just filled. Cost an afternoon to see once.
    """
    handler = HTML.split("document.addEventListener('click'")[1].split("}, ")[1][:20]
    assert handler.startswith("true"), (
        "the outside-click listener must be registered in the capture phase, "
        f"got {handler!r}"
    )


# --- reading vs doing ------------------------------------------------------


def test_the_task_list_is_shown_never_edited():
    """It's her judgement about what you should do next. A checkbox here would
    make it yours — a product decision hiding in two lines of DOM code."""
    render = HTML.split("bind('tasks-btn'")[1].split("// --- notices")[0]
    for control in ("createElement('input')", "createElement('button')", "checkbox"):
        assert control not in render, f"the task panel builds a {control}"


def test_the_notices_log_is_shown_never_edited():
    render = HTML.split("bind('notices-btn'")[1].split("refreshNoticeCount();")[0]
    for control in ("createElement('input')", "createElement('button')", "checkbox"):
        assert control not in render


@pytest.mark.parametrize("endpoint", ["/api/tasks", "/api/notifications"])
def test_the_page_never_writes_to_a_read_only_endpoint(endpoint):
    for script in CODE:
        for match in re.finditer(
                r"fetch\(\s*'" + re.escape(endpoint) + r"[^']*'\s*(?:,\s*\{([^}]*)\})?", script):
            assert "method" not in (match.group(1) or ""), f"{endpoint} called with a method"


def test_unseen_notices_are_tracked_on_the_device():
    """"Seen" is a property of this phone, not of the notice — and marking one
    read on the server would be a write to a log that only reads."""
    assert "localStorage.setItem('lastNotice'" in HTML
    assert "localStorage.getItem('lastNotice')" in HTML


# --- destructive things ----------------------------------------------------


def test_clearing_chats_takes_two_deliberate_steps():
    """The row that starts it sits in a panel you'd be poking around in."""
    row_handler = HTML.split("content.append(row('Clear chats…'")[1].split("}")[0]
    assert "confirmClear" in row_handler
    assert "/api/db/clear-history" not in row_handler, "one tap must not delete"

    confirm = HTML.split("function confirmClear()")[1].split("async function clearNow")[0]
    assert "Delete them" in confirm
    assert "will be deleted" in confirm


def test_the_delete_request_says_confirm_explicitly():
    flow = HTML.split("async function clearNow()")[1]
    assert "/api/db/clear-history" in flow
    assert "confirm: true" in flow


def test_the_page_offers_no_way_to_skip_the_backup():
    """The CLI has --no-backup. Over HTTP that shouldn't exist at all."""
    assert "no_backup" not in HTML and "no-backup" not in HTML


def test_the_stale_conversation_id_is_dropped_after_clearing():
    flow = HTML.split("async function clearNow()")[1]
    assert "removeItem('conversationId')" in flow


def test_restarting_asks_first():
    """One stray tap shouldn't take the server down mid-answer."""
    restart = HTML.split("bind('restart-btn'")[1].split("async function health")[0]
    assert "Restart now" in restart
    assert "/api/restart" not in restart, "the button must only open the panel"
    # Passing restartNow as the action is right; calling it here is not. The
    # parens are the whole difference between a confirmation and a hair
    # trigger.
    assert "restartNow()" not in restart, "the button fires the restart itself"


def test_the_restart_flow_waits_for_a_new_process():
    """Polling for any answer would catch the old process still shutting down."""
    flow = HTML.split("async function restartNow()")[1]
    assert "/api/restart" in flow
    assert "no-store" in HTML, "a cached health response would fake a recovery"
    assert re.search(r"\.started\s*>\s*before", flow), (
        "nothing compares the new start time against the old one"
    )
    assert "location.reload()" in flow, (
        "the usual reason to restart is that the code changed, and this page is "
        "part of that code"
    )
    assert "did not come back" in flow


# --- taken from the parallel branch ----------------------------------------


def test_new_text_does_not_drag_you_back_down():
    """A real bug this page had, found on a parallel branch.

    Every arriving chunk called log.scrollTop = log.scrollHeight
    unconditionally, so scrolling up to re-read something mid-reply was a
    fight you lost several times a second.
    """
    assert "function atBottom()" in HTML
    unguarded = [
        line for line in HTML.splitlines()
        if "scrollTop = log.scrollHeight" in line
        and "followIfAtBottom" not in line
        and "openConversation" not in line
    ]
    assert len(unguarded) <= 2, f"unguarded auto-scroll: {unguarded}"
    assert "followIfAtBottom" in HTML


def test_the_stream_checks_before_following():
    """The guard has to be read *before* the new text lands.

    Measuring afterwards always says 'not at the bottom', because the content
    just got taller — so the check would disable itself.
    """
    stream = HTML.split("ev.type === 'text'")[1].split("else if")[0]
    assert stream.index("atBottom()") < stream.index("textContent +="), (
        "the position is being measured after the text was added"
    )


def test_the_page_does_not_rubber_band():
    assert "overscroll-behavior:none" in HTML.replace(" ", "")


def test_tapping_the_input_does_not_zoom_the_page():
    viewport = [l for l in HTML.splitlines() if 'name="viewport"' in l][0]
    assert "maximum-scale=1" in viewport
    assert "user-scalable=no" in viewport


def test_the_chats_panel_is_called_recent_and_can_start_a_new_one():
    """Starting a fresh thread lives next to the list of existing ones."""
    chats = HTML.split("bind('chats'")[1].split("async function openConversation")[0]
    assert "'Recent'" in chats
    assert "'+ New'" in chats
    assert "newConversation" in chats


def test_the_open_thread_is_marked_in_the_list():
    chats = HTML.split("bind('chats'")[1].split("async function openConversation")[0]
    assert "current" in chats


# --- the manifest and what it promises -------------------------------------


def test_manifest_icons_exist_on_disk():
    import json

    manifest = json.loads((WEB / "manifest.json").read_text())
    assert manifest["icons"], "no icons declared"
    for icon in manifest["icons"]:
        assert (WEB / "static" / Path(icon["src"]).name).exists(), f"{icon['src']} is missing"


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
    assert "askToken" in HTML
    assert "token-input" in HTML
    assert "searchParams.get('token')" in HTML, "no ?token= path for a Shortcut or QR code"
