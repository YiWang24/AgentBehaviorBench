"""Upstream helper package.

Upstream ships `helpers/` without an `__init__.py` and relies on the repository
root being on `sys.path`. This vendored copy adds the file so setuptools
installs it as a real package; the modules themselves are unchanged.
"""
