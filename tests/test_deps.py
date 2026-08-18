"""Requirements checking, and the reload that depends on it.

The interesting case isn't a missing package — pip tells you about those. It's
a package that is installed, is the right version, and still doesn't import
because something underneath it is missing. That shows up as the server dying
at startup with a traceback naming a module nobody recognises, which is a much
worse thing to debug from a phone than "idna is missing".
"""

from pathlib import Path

import pytest

from sevanya import deps, lifecycle, tools


@pytest.fixture
def project_with(tmp_path):
    def make(contents: str) -> Path:
        (tmp_path / "requirements.txt").write_text(contents)
        return tmp_path
    return make


# --- reading the file ------------------------------------------------------


def test_comments_blanks_and_pip_options_are_ignored(project_with):
    root = project_with(
        "# a comment\n"
        "\n"
        "anthropic>=0.40.0\n"
        "fastapi>=0.110.0   # trailing comment\n"
        "--extra-index-url https://example.com/simple\n"
        "-r other.txt\n"
    )
    assert deps.read(deps.requirements_path(root)) == ["anthropic>=0.40.0", "fastapi>=0.110.0"]


def test_a_missing_requirements_file_is_not_a_failure(tmp_path):
    ok, report = deps.ensure(tmp_path)
    assert ok
    assert "no requirements.txt" in report


def test_an_empty_requirements_file_is_not_a_failure(project_with):
    ok, report = deps.ensure(project_with("# nothing here\n"))
    assert ok
    assert "nothing to check" in report


@pytest.mark.parametrize("line,expected", [
    ("anthropic>=0.40.0", "anthropic"),
    ("anthropic", "anthropic"),
    ("uvicorn[standard]>=0.27", "uvicorn"),
    ("fastapi==0.110.0", "fastapi"),
    ("httpx!=0.28.0", "httpx"),
])
def test_the_package_name_is_pulled_out_of_a_requirement(line, expected):
    assert deps._name_of(line) == expected


# --- checking --------------------------------------------------------------


def test_installed_requirements_come_back_clean():
    entries = deps.check(["anthropic>=0.40.0", "fastapi>=0.110.0"])
    assert [e["problem"] for e in entries] == [None, None]
    assert all(e["installed"] for e in entries)


def test_a_missing_package_is_reported():
    entry = deps.check(["definitely-not-a-real-package-xyz"])[0]
    assert entry["problem"] == "not installed"


def test_a_version_that_is_too_old_is_reported():
    """Present isn't the same as adequate."""
    entry = deps.check(["anthropic>=99999.0.0"])[0]
    assert entry["problem"] is not None
    assert "needs" in entry["problem"]


def test_installed_but_unimportable_is_caught(monkeypatch):
    """The failure that otherwise appears as a traceback at startup."""
    monkeypatch.setattr(deps, "_modules_for", lambda name: ["anthropic"])

    real_import = deps.__builtins__["__import__"] if isinstance(deps.__builtins__, dict) else __import__

    def broken(name, *args, **kwargs):
        if name == "anthropic":
            raise ModuleNotFoundError("No module named 'idna'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setitem(__builtins__ if isinstance(__builtins__, dict) else __builtins__.__dict__,
                        "__import__", broken)
    entry = deps.check(["anthropic>=0.40.0"])[0]
    assert "won't import" in entry["problem"]
    assert "idna" in entry["problem"]


def test_ensure_reports_problems_without_installing_when_asked_not_to(project_with, monkeypatch):
    called = []
    monkeypatch.setattr(deps, "install", lambda path: called.append(path) or (True, ""))
    ok, report = deps.ensure(project_with("definitely-not-a-real-package-xyz\n"),
                             install_missing=False)
    assert not ok
    assert not called, "install_missing=False must not run pip"
    assert "not installed" in report


def test_ensure_installs_and_rechecks(project_with, monkeypatch):
    """pip exiting 0 does not prove the thing imports.

    Re-checking afterwards is the difference between "installed" and "working",
    which is the whole reason this module exists.
    """
    rechecked = []
    monkeypatch.setattr(deps, "install", lambda path: (True, "Successfully installed"))

    calls = {"n": 0}

    def check(lines):
        calls["n"] += 1
        if calls["n"] == 1:
            return [{"line": lines[0], "name": "thing", "installed": None, "problem": "not installed"}]
        rechecked.append(True)
        return [{"line": lines[0], "name": "thing", "installed": "1.0", "problem": None}]

    monkeypatch.setattr(deps, "check", check)
    ok, report = deps.ensure(project_with("thing\n"))
    assert ok and rechecked
    assert "installed thing" in report


def test_a_failed_pip_run_is_reported_not_swallowed(project_with, monkeypatch):
    monkeypatch.setattr(deps, "install", lambda path: (False, "ERROR: could not build wheel"))
    monkeypatch.setattr(deps, "check", lambda lines: [
        {"line": "x", "name": "x", "installed": None, "problem": "not installed"}])
    ok, report = deps.ensure(project_with("x\n"))
    assert not ok
    assert "pip install failed" in report
    assert "could not build wheel" in report


def test_still_broken_after_pip_is_reported(project_with, monkeypatch):
    monkeypatch.setattr(deps, "install", lambda path: (True, "fine"))
    monkeypatch.setattr(deps, "check", lambda lines: [
        {"line": "x", "name": "x", "installed": None, "problem": "not installed"}])
    ok, report = deps.ensure(project_with("x\n"))
    assert not ok
    assert "still wrong" in report


# --- the reload tool -------------------------------------------------------


@pytest.fixture
def call(store, monkeypatch):
    conversation = store.new_conversation()
    restarts = []
    monkeypatch.setattr(lifecycle, "schedule_restart", lambda *a, **k: restarts.append(True))

    def invoke(**arguments):
        output, is_error = tools.dispatch("reload", arguments, store=store,
                                          conversation_id=conversation)
        return output, is_error, restarts

    return invoke


def test_reload_checks_then_restarts(call, monkeypatch, store):
    monkeypatch.setattr(lifecycle, "can_restart", lambda: True)
    monkeypatch.setattr(tools.deps, "ensure", lambda root, install_missing=True: (True, "all good"))

    out, is_error, restarts = call()
    assert not is_error
    assert "all good" in out and "Restarting" in out
    assert restarts == [True]


def test_reload_refuses_to_restart_into_a_broken_environment(call, monkeypatch):
    """It would come back only far enough to crash on import.

    And then there's nothing listening to explain why — which is the worst
    possible outcome for a button you press when you're not at the machine.
    """
    monkeypatch.setattr(lifecycle, "can_restart", lambda: True)
    monkeypatch.setattr(tools.deps, "ensure",
                        lambda root, install_missing=True: (False, "fastapi: not installed"))

    out, is_error, restarts = call()
    assert not is_error
    assert "Not restarting" in out
    assert "fastapi: not installed" in out
    assert restarts == [], "it restarted despite the environment being broken"


def test_reload_in_the_terminal_says_there_is_nothing_to_restart(call, monkeypatch):
    monkeypatch.setattr(lifecycle, "can_restart", lambda: False)
    monkeypatch.setattr(tools.deps, "ensure", lambda root, install_missing=True: (True, "all good"))

    out, _, restarts = call()
    assert "Nothing to restart" in out
    assert restarts == []


def test_reload_records_what_it_did(call, monkeypatch, store):
    """The restart takes the transcript view with it.

    Whatever the dependency check found has to survive somewhere the user can
    still read afterwards.
    """
    monkeypatch.setattr(lifecycle, "can_restart", lambda: True)
    monkeypatch.setattr(tools.deps, "ensure",
                        lambda root, install_missing=True: (True, "installed httpx"))

    call()
    kinds = [row["kind"] for row in store.notifications()]
    messages = " ".join(row["message"] for row in store.notifications())
    assert "requirements" in kinds and "restart" in kinds
    assert "installed httpx" in messages


def test_a_failed_check_is_recorded_as_a_failure(call, monkeypatch, store):
    monkeypatch.setattr(lifecycle, "can_restart", lambda: True)
    monkeypatch.setattr(tools.deps, "ensure", lambda root, install_missing=True: (False, "broken"))
    call()
    assert "requirements-failed" in [row["kind"] for row in store.notifications()]


def test_reload_can_be_asked_to_only_report(call, monkeypatch):
    seen = {}
    monkeypatch.setattr(lifecycle, "can_restart", lambda: True)

    def ensure(root, install_missing=True):
        seen["install"] = install_missing
        return True, "checked"

    monkeypatch.setattr(tools.deps, "ensure", ensure)
    call(install=False)
    assert seen["install"] is False
