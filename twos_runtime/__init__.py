"""TWOS local runtime foundation."""

__all__ = ["__version__"]

__version__ = "1.0.3"

# This patch does not change the installation/database schema. Preserve an
# existing 1.0.1/1.0.2 bindings verbatim; unrelated versions require maintenance.
INSTALLATION_COMPATIBLE_VERSIONS = frozenset({"1.0.1", "1.0.2", "1.0.3"})
