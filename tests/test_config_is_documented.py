"""Every setting a user can change has to appear in the README.

The README's configuration table opens by claiming every variable has a working
default — a claim that is only useful if the table is complete. It had drifted:
four settings existed in code and appeared nowhere, including SYSTEM_PROMPT,
which is the entire personality knob and was undiscoverable.

This is the same guard as tests/test_spec_traceability.py, aimed at the same
failure: documentation asserting something the code does not back.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
CONFIG = ROOT / "app" / "core" / "config.py"

# Set by docker-compose.yml on the service, never by a person editing .env.
# Documenting it would invite someone to change it and break the container
# networking it encodes.
INTERNAL_ONLY = {"MONGO_URI"}


def _settings_fields() -> set[str]:
    body = CONFIG.read_text().split("class Settings")[1]
    return {name.upper() for name in re.findall(r"^    ([a-z][a-z0-9_]*):", body, re.M)}


def test_every_setting_appears_in_the_readme() -> None:
    documented = set(re.findall(r"`([A-Z][A-Z0-9_]+)`", README.read_text()))
    missing = sorted(_settings_fields() - documented - INTERNAL_ONLY)

    assert not missing, (
        f"settings absent from the README configuration table: {missing}. "
        "The table claims to be complete, so either document them or mark them "
        "internal in INTERNAL_ONLY with a reason."
    )


def test_every_setting_appears_in_the_example_env() -> None:
    example = (ROOT / ".env.example").read_text()
    declared = {line.split("=")[0].strip() for line in example.splitlines() if "=" in line}
    missing = sorted(_settings_fields() - declared - INTERNAL_ONLY)

    assert not missing, f"settings absent from .env.example: {missing}"
