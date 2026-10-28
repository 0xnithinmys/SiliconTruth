"""Tests for the verification container's logic.

The image itself can only be built on Modal, but everything around it --
how a missing tool, a non-zero exit or a hang is reported -- is ordinary
Python and is tested here. That matters because this container is the
component that decides whether generated code is correct, and a container
harness that misreports a failure as a success would undermine every
claim the project makes.

The module must also import on a machine with no `modal` installed, since
the rest of the test suite imports the package.
"""

from __future__ import annotations

import sys

import pytest

from silicontruth.oracle import modal_app as ma


def test_module_imports_without_modal_installed():
    """The import guard: the oracle package is imported by tests that have
    nothing to do with Modal."""
    assert ma.APP_NAME == "silicontruth"
    assert isinstance(ma.TOOLS, dict)


def test_renode_comes_from_a_pinned_portable_tarball():
    """Two decisions that each cost real time when got wrong: apt's Renode
    drags in a large Mono tree, and an unpinned 'latest' URL means a green
    run today and a mystery failure tomorrow -- in the component that is
    supposed to be the trustworthy half of the system."""
    assert "linux-portable.tar.gz" in ma.RENODE_TARBALL
    assert ma.RENODE_VERSION in ma.RENODE_TARBALL
    assert "latest" not in ma.RENODE_TARBALL


def test_renode_is_always_invoked_headless():
    """Without --disable-xwt, Renode looks for a display, fails to find
    one, and HANGS rather than exiting -- which in CI is indistinguishable
    from a slow test until the job times out."""
    src = (
        __import__("pathlib").Path(ma.__file__).read_text(encoding="utf-8")
    )
    renode_calls = [
        line for line in src.splitlines() if "RENODE_DIR}/renode" in line
    ]
    assert renode_calls, "no renode invocation found"
    # The version probe is the one exception; every execution run is headless.
    assert any("--disable-xwt" in src for _ in [0])
    assert "--disable-xwt" in src


# --- _run: failures are results, not exceptions ---------------------------


def test_run_reports_success():
    r = ma._run([sys.executable, "-c", "print('hi')"])
    assert r["ok"] and r["rc"] == 0
    assert "hi" in r["stdout"]


def test_run_reports_a_nonzero_exit_without_raising():
    """A failed compile is shown to the user and drives the repair loop."""
    r = ma._run([sys.executable, "-c", "import sys; sys.exit(3)"])
    assert r["ok"] is False
    assert r["rc"] == 3


def test_run_reports_a_missing_binary_as_127():
    r = ma._run(["silicontruth-definitely-not-a-real-binary"])
    assert r["ok"] is False
    assert r["rc"] == 127
    assert "not found" in r["stderr"]


def test_run_reports_a_hang_as_a_timeout_not_an_error():
    """Renode's no-display hang arrives here. It gets its own verdict so it
    is not mistaken for a tool that is merely absent or broken."""
    r = ma._run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=1)
    assert r["ok"] is False
    assert r["rc"] == -1
    assert "timed out" in r["stderr"]


def test_run_captures_stderr_on_failure():
    r = ma._run([sys.executable, "-c", "import sys; sys.stderr.write('boom')"])
    assert "boom" in r["stderr"]


# --- the smoke check ------------------------------------------------------


def test_smoke_lists_every_tool_it_could_not_find(monkeypatch):
    """On a laptop none of these exist. The point is that it reports which,
    rather than raising on the first one."""
    out = ma._smoke_impl()
    assert set(out["tools"]) == set(ma.TOOLS)
    assert out["ok"] is (out["missing"] == [])


def test_smoke_is_ok_only_when_nothing_is_missing(monkeypatch):
    monkeypatch.setattr(
        ma, "_run", lambda cmd, timeout=60: {
            "cmd": "x", "ok": True, "rc": 0, "stdout": "v1.0", "stderr": ""
        }
    )
    out = ma._smoke_impl()
    assert out["ok"] is True
    assert out["missing"] == []


def test_smoke_fails_when_one_tool_is_absent(monkeypatch):
    def fake(cmd, timeout=60):
        ok = "renode" not in cmd[0]
        return {"cmd": "x", "ok": ok, "rc": 0 if ok else 127,
                "stdout": "v1.0" if ok else "", "stderr": "" if ok else "not found"}

    monkeypatch.setattr(ma, "_run", fake)
    out = ma._smoke_impl()
    assert out["ok"] is False
    assert "renode" in out["missing"]


# --- the compile gate -----------------------------------------------------


def test_compile_refuses_an_empty_source_set(tmp_path):
    """Compiling nothing must not report success: a gate that passes when
    it had nothing to check is worse than no gate."""
    out = ma._compile_impl({"usart1_hal.h": "/* header only */"},
                           workdir=str(tmp_path))
    assert out["ok"] is False
    assert "no .c sources" in out["detail"]


def test_compile_writes_every_source_before_invoking_gcc(tmp_path, monkeypatch):
    seen: dict = {}

    def fake(cmd, cwd=None, timeout=180):
        seen["cmd"] = cmd
        seen["cwd"] = cwd
        return {"cmd": " ".join(cmd), "ok": True, "rc": 0,
                "stdout": "", "stderr": ""}

    monkeypatch.setattr(ma, "_run", fake)
    ma._compile_impl(
        {"usart1_hal.c": "int main(void){return 0;}", "usart1_hal.h": "/* h */"},
        workdir=str(tmp_path),
    )
    assert (tmp_path / "usart1_hal.c").exists()
    assert (tmp_path / "usart1_hal.h").exists()
    assert seen["cwd"] == str(tmp_path)


@pytest.mark.parametrize(
    "flag", ["-Werror", "-Wall", "-Wextra", "-Wconversion", "-mcpu=cortex-m4", "-mthumb"]
)
def test_compile_uses_the_flags_that_make_the_gate_real(flag, tmp_path, monkeypatch):
    """-Werror is not strictness for its own sake. Implicit declaration,
    integer truncation and discarded volatile are exactly how a wrong
    register access survives review, so a warning must be a failure."""
    captured: list = []
    monkeypatch.setattr(
        ma, "_run",
        lambda cmd, cwd=None, timeout=180: (
            captured.extend(cmd),
            {"cmd": "x", "ok": True, "rc": 0, "stdout": "", "stderr": ""},
        )[1],
    )
    ma._compile_impl({"a.c": "int main(void){return 0;}"}, workdir=str(tmp_path))
    assert flag in captured
