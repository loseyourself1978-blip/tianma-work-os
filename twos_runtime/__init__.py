"""TWOS local runtime foundation."""

__all__ = ["__version__"]

__version__ = "1.0.15"

# This patch does not change the installation/database schema. Preserve
# existing 1.0.1–1.0.8 bindings verbatim; unrelated versions require maintenance.
INSTALLATION_COMPATIBLE_VERSIONS = frozenset({"1.0.1", "1.0.2", "1.0.3", "1.0.4", "1.0.5", "1.0.6", "1.0.7", "1.0.8", "1.0.9", "1.0.10", "1.0.11", "1.0.12", "1.0.13", "1.0.14", "1.0.15"})
