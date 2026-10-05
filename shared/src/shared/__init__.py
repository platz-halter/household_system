# Single source of truth for the version every service reports (FastAPI's
# `version=` on each app, and each /health response) and that both
# frontends display in Settings — defined once here rather than copied
# into 5 pyproject.toml files' worth of places that could drift apart.
# Bump this on a real release; the pyproject.toml `version` fields are
# kept in sync by hand alongside it (no publish step reads them — this
# is a Docker-deployed app, not a published package — so there's no
# tooling to automate the two staying in sync; just change both together).
__version__ = "1.0.1"
