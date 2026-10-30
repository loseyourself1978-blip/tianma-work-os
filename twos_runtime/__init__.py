"""TWOS local runtime foundation."""

__all__ = ["__version__"]

__version__ = "1.0.3"

# This patch does not change the installation/database schema. Preserve an
# existing 1.0.1 binding verbatim; unrelated versions still require maintenance.
INSTALLATION_COMPATIBLE_VERSIONS = frozenset({"1.0.1", __version__})
