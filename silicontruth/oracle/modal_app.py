"""The verification container: where compiling and emulating actually happen.

Nothing in SiliconTruth may claim a driver is correct until that driver has
been compiled by a real toolchain and executed against a real emulator. On
a Windows laptop with 5.9 GB of RAM neither is available, so both live
here, in a Linux image with the toolchain pinned.

Deploy:
    modal deploy silicontruth/oracle/modal_app.py
Smoke the toolchain (the riskiest step, do it first):
    modal run silicontruth/oracle/modal_app.py::smoke

Two notes that cost real time if ignored:

* Renode comes from the **portable tarball**, not from apt. The packaged
  build pulls a large Mono dependency tree and has repeatedly been a time
  sink; the portable tarball is self-contained and pinned by URL here.

* Renode runs with `--disable-xwt`. Without it, it tries to open a GUI,
  finds no display, and hangs rather than failing -- which in CI looks
  identical to a slow test until the job times out.

The functions return structured verdicts rather than raising, because the
caller is the web UI, and "the compile failed, here is the error" is a
result to display, not an exception to swallow.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from typing import Any

try:
    import modal
except ImportError:  # pragma: no cover - import guard for local test runs
    modal = None  # type: ignore[assignment]

APP_NAME = "silicontruth"

# Pinned. An unpinned "latest" URL means a green run today and a mystery
# failure tomorrow, in the one component that is supposed to be the
# trustworthy half of the system.
RENODE_VERSION = "1.15.3"
RENODE_TARBALL = (
    f"https://github.com/renode/renode/releases/download/v{RENODE_VERSION}/"
    f"renode-{RENODE_VERSION}.linux-portable.tar.gz"
)
RENODE_DIR = "/opt/renode"

TOOLS: dict[str, list[str]] = {
    "renode": [f"{RENODE_DIR}/renode", "--version"],
    "arm-none-eabi-gcc": ["arm-none-eabi-gcc", "--version"],
    "rustc": ["rustc", "--version"],
    "cargo": ["cargo", "--version"],
    "svd2rust": ["svd2rust", "--version"],
    "z3": ["z3", "--version"],
    "python3": ["python3", "--version"],
}


def _image():
    if modal is None:  # pragma: no cover
        raise RuntimeError("modal is not installed; pip install modal")
    return (
        modal.Image.debian_slim(python_version="3.12")
        .apt_install(
            "curl",
            "ca-certificates",
            "xz-utils",
            "gcc-arm-none-eabi",
            "binutils-arm-none-eabi",
            "libnewlib-arm-none-eabi",
            "z3",
            # Renode's portable build still needs these shared libraries
            # present even though it ships its own runtime.
            "libicu-dev",
            "libgtk2.0-0",
            "screen",
            "policykit-1",
            "sigrok-cli",
        )
        .run_commands(
            f"mkdir -p {RENODE_DIR}",
            f"curl -fsSL {RENODE_TARBALL} -o /tmp/renode.tar.gz",
            f"tar -xzf /tmp/renode.tar.gz -C {RENODE_DIR} --strip-components=1",
            "rm /tmp/renode.tar.gz",
            f"test -x {RENODE_DIR}/renode",
        )
        .run_commands(
            "curl -fsSL https://sh.rustup.rs -o /tmp/rustup.sh",
            "sh /tmp/rustup.sh -y --default-toolchain stable --profile minimal",
            "/root/.cargo/bin/rustup target add thumbv7em-none-eabihf",
            "/root/.cargo/bin/rustup target add riscv32imac-unknown-none-elf",
            "/root/.cargo/bin/cargo install svd2rust --locked --version 0.33.5",
            "ln -sf /root/.cargo/bin/* /usr/local/bin/",
        )
        .pip_install("z3-solver==4.13.0.0", "pydantic>=2.7")
    )


if modal is not None:  # pragma: no cover - only meaningful on Modal
    app = modal.App(APP_NAME)
    image = _image()
else:
    app = None
    image = None


def _run(cmd: list[str], *, cwd: str | None = None, timeout: int = 120) -> dict:
    """Run a command and report it. Never raises on a non-zero exit.

    A failed compile is a RESULT -- it is shown to the user and drives the
    repair loop -- not an exception to be swallowed somewhere up the stack.
    """
    try:
        p = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return {"cmd": shlex.join(cmd), "ok": False, "rc": 127,
                "stdout": "", "stderr": "not found"}
    except subprocess.TimeoutExpired:
        # Renode without --disable-xwt hangs here rather than failing, so a
        # timeout gets its own verdict instead of being reported as an error.
        return {"cmd": shlex.join(cmd), "ok": False, "rc": -1,
                "stdout": "", "stderr": f"timed out after {timeout}s"}
    return {
        "cmd": shlex.join(cmd),
        "ok": p.returncode == 0,
        "rc": p.returncode,
        "stdout": p.stdout[-4000:],
        "stderr": p.stderr[-4000:],
    }


def _smoke_impl() -> dict[str, Any]:
    """Version-check every tool. Pure, so it is testable without Modal."""
    results = {name: _run(cmd, timeout=60) for name, cmd in TOOLS.items()}
    missing = [n for n, r in results.items() if not r["ok"]]
    return {
        "ok": not missing,
        "missing": missing,
        "tools": {
            n: (r["stdout"] or r["stderr"]).strip().splitlines()[:1]
            for n, r in results.items()
        },
    }


def _compile_impl(sources: dict[str, str], workdir: str = "/tmp/build") -> dict:
    """Compile the generated C for Cortex-M4 with -Werror.

    -Werror is not strictness for its own sake. The warnings that matter
    here -- implicit declaration, integer truncation, discarded volatile --
    are exactly how a wrong register access gets past review, so a warning
    has to be a failure or the gate is decorative.
    """
    import os

    os.makedirs(workdir, exist_ok=True)
    for name, text in sources.items():
        with open(os.path.join(workdir, name), "w", encoding="utf-8") as fh:
            fh.write(text)

    cfiles = sorted(n for n in sources if n.endswith(".c"))
    if not cfiles:
        return {"ok": False, "stage": "compile", "detail": "no .c sources given"}

    cmd = [
        "arm-none-eabi-gcc",
        "-mcpu=cortex-m4",
        "-mthumb",
        "-c",
        "-Os",
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-Wconversion",
        *cfiles,
    ]
    r = _run(cmd, cwd=workdir, timeout=180)
    return {"ok": r["ok"], "stage": "compile", **r}


if modal is not None:  # pragma: no cover
    @app.function(image=image, timeout=600)
    def smoke() -> dict:
        return _smoke_impl()

    @app.function(image=image, timeout=900)
    def compile_c(sources: dict[str, str]) -> dict:
        return _compile_impl(sources)

    @app.function(image=image, timeout=900)
    def run_renode(files: dict[str, str], script: str = "run_test.resc") -> dict:
        """Execute a generated peripheral model and judge its MMIO trace.

        --disable-xwt is mandatory: without it Renode looks for a display,
        does not find one, and hangs instead of failing.
        """
        import os

        work = "/tmp/renode"
        os.makedirs(work, exist_ok=True)
        for name, text in files.items():
            path = os.path.join(work, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)

        r = _run(
            [f"{RENODE_DIR}/renode", "--disable-xwt", "--console", "-e",
             f"include @{os.path.join(work, script)}"],
            cwd=work,
            timeout=300,
        )
        from silicontruth.oracle.renode_oracle import evaluate

        verdict = evaluate(r["stdout"] + "\n" + r["stderr"])
        return {
            "ok": verdict.passed,
            "stage": "emulate",
            "renode": r,
            "verdict": {
                "passed": verdict.passed,
                "reason": getattr(verdict, "reason", ""),
                "transactions": len(getattr(verdict, "transactions", []) or []),
            },
        }

    @app.local_entrypoint()
    def main() -> None:
        out = smoke.remote()
        print(json.dumps(out, indent=2))
        if not out["ok"]:
            raise SystemExit(f"missing tools: {out['missing']}")
