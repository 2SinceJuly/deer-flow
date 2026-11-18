from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

# Providers whose SDK is a harness extra, so the published image needs the same
# name as a backend extra for `docker build --build-arg UV_EXTRAS=<name>` to
# resolve against uv.lock. See the `opensandbox` extra in the harness pyproject.
REMOTE_SANDBOX_EXTRAS = ("opensandbox", "boxlite", "tenki", "boxd")


def test_boxlite_is_optional_harness_dependency() -> None:
    """BoxLite should not make core harness installs platform-dependent."""
    pyproject_path = Path(__file__).resolve().parents[1] / "packages" / "harness" / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    core_dependencies = pyproject["project"]["dependencies"]
    optional_dependencies = pyproject["project"]["optional-dependencies"]

    assert not any(dep.startswith("boxlite") for dep in core_dependencies)
    assert any(dep.startswith("boxlite>=0.9.7") for dep in optional_dependencies["boxlite"])


def test_opensandbox_is_optional_harness_dependency() -> None:
    """OpenSandbox should be installed only when its provider is selected."""
    pyproject_path = Path(__file__).resolve().parents[1] / "packages" / "harness" / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    core_dependencies = pyproject["project"]["dependencies"]
    optional_dependencies = pyproject["project"]["optional-dependencies"]

    assert not any(dep.startswith("opensandbox") for dep in core_dependencies)
    assert optional_dependencies["opensandbox"] == ["opensandbox>=0.1.15,<0.2.0"]


def test_boxd_is_optional_harness_dependency() -> None:
    """The boxd SDK should be installed only when its provider is selected."""
    pyproject_path = Path(__file__).resolve().parents[1] / "packages" / "harness" / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    core_dependencies = pyproject["project"]["dependencies"]
    optional_dependencies = pyproject["project"]["optional-dependencies"]

    assert not any(dep.startswith("boxd") for dep in core_dependencies)
    assert optional_dependencies["boxd"] == ["boxd>=0.3.2"]


@pytest.mark.parametrize("extra", REMOTE_SANDBOX_EXTRAS)
def test_backend_reexports_remote_sandbox_extras(extra: str) -> None:
    """A sandbox SDK the harness makes optional stays installable through the backend.

    ``backend/Dockerfile`` installs with ``uv sync --locked --extra <name>``, so it
    can only select an extra the backend project itself declares; a harness-only
    extra fails the build. Re-exporting keeps the resolved version coming from
    uv.lock instead of an out-of-lock install at container start.
    """
    pyproject = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["optional-dependencies"][extra] == [f"deerflow-harness[{extra}]"]


def test_locked_install_accepts_each_remote_sandbox_extra(tmp_path: Path) -> None:
    """`uv sync --locked --extra <name>` resolves, which is what the image build runs.

    The table assertion above can pass while uv.lock is stale, and a stale lock
    fails the locked sync with "extra is not defined". Run uv against a copy of
    the project so the repo's own environment is untouched.
    """
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not installed")

    workdir = tmp_path / "backend"
    workdir.mkdir()
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copy2(BACKEND_ROOT / name, workdir / name)
    # `uv sync` resolves the local workspace members named in pyproject.toml.
    packages = BACKEND_ROOT / "packages"
    if packages.is_dir():
        (workdir / "packages").symlink_to(packages, target_is_directory=True)

    env = os.environ.copy()
    env["UV_PROJECT_ENVIRONMENT"] = str(tmp_path / "env")
    env["UV_OFFLINE"] = "1"
    # The lock targets the interpreters the image ships (3.12/3.13). Resolving
    # against whatever interpreter runs the suite fails on unrelated packages
    # that publish no wheel for it, which says nothing about the extra.
    env["UV_PYTHON"] = "3.12"

    for extra in REMOTE_SANDBOX_EXTRAS:
        result = subprocess.run(
            [uv, "sync", "--locked", "--dry-run", "--extra", extra],
            cwd=workdir,
            env=env,
            capture_output=True,
            text=True,
        )
        combined = result.stdout + result.stderr
        if "No solution found" in combined or "Failed to download" in combined or "Can't find Python" in combined:
            pytest.skip(f"offline uv cannot resolve {extra}: {combined.strip()[-200:]}")
        assert result.returncode == 0, combined
        assert "is not defined in the `optional-dependencies` table" not in combined


# Where the provider tells readers how to install its SDK. Both name the image
# path, because `pip install` alone leaves container users with the published
# image, which is built with `UV_EXTRAS=postgres` only.
INSTALL_DOCS = (
    Path("docs") / "CONFIGURATION.md",
    Path("packages") / "harness" / "deerflow" / "community" / "opensandbox" / "README.md",
)


@pytest.mark.parametrize("doc", INSTALL_DOCS, ids=lambda p: p.name)
def test_opensandbox_install_docs_name_the_image_path(doc: Path) -> None:
    """The documented image build selects the extra the backend now declares.

    ``pip install`` is not an option inside the production image, so a docs page
    that only shows it sends container users to an install the image cannot do.
    """
    text = (BACKEND_ROOT / doc).read_text(encoding="utf-8")

    assert 'pip install "deerflow-harness[opensandbox]"' in text
    assert "--build-arg UV_EXTRAS=opensandbox" in text
