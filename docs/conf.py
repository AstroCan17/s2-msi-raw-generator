# Copyright 2026 Can Deniz Kaya
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Sphinx configuration for the Sentinel-2 MSI Synthetic Raw Data Generator documentation."""

import os
import sys

sys.path.insert(0, os.path.abspath(".."))

# -- Project information ------------------------------------------------------
project = "s2-e2es"
copyright = "2026 Can Deniz Kaya"
author = "Can Deniz Kaya"
# Set by the CI pipeline (`SPHINX_RELEASE`); falls back to the package version.
release = os.environ.get("SPHINX_RELEASE", "0.3.0.dev0")

# -- General configuration ----------------------------------------------------
extensions = [
    "myst_parser",                 # Markdown (the DRD set is markdown)
    "sphinxcontrib.apidoc",        # auto-run sphinx-apidoc on the package
    "sphinx.ext.autodoc",          # API docs from docstrings
    "sphinx.ext.napoleon",         # lenient NumPy/Google docstring parsing
    "sphinx_autodoc_typehints",    # type hints in the API
    "sphinxcontrib.mermaid",       # diagrams
]

source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
# Cross-reference resolution is best-effort for a first publish (external types
# such as numpy.ndarray would otherwise fail the build).
nitpicky = False

# -- MyST (Markdown) ----------------------------------------------------------
myst_enable_extensions = ["linkify", "colon_fence", "deflist"]
myst_linkify_fuzzy_links = False
myst_heading_anchors = 3
# Render ```mermaid fenced blocks as the mermaid directive (so the same fence
# also renders natively on GitLab's markdown view).
myst_fence_as_directive = ["mermaid"]

# -- API docs (sphinxcontrib.apidoc) -----------------------------------------
apidoc_module_dir = "../s2_e2es"
apidoc_output_dir = "api"
apidoc_module_first = True
apidoc_toc_file = False
apidoc_separate_modules = False
autodoc_typehints = "signature"
autodoc_mock_imports = ["zarr", "PIL", "imageio", "matplotlib"]  # optional runtime deps
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
}
napoleon_google_docstring = True
napoleon_numpy_docstring = True

# -- HTML output --------------------------------------------------------------
html_theme = "sphinx_book_theme"
html_title = "Sentinel-2 MSI Synthetic Raw Data Generator"
html_theme_options = {
    "repository_url": "https://gitlab.eopf.copernicus.eu/e2es/s2-e2es",
    "repository_branch": "main",
    "path_to_docs": "docs",
    "use_repository_button": True,
    "use_issues_button": True,
    "home_page_in_toc": False,
    "logo": {"text": "s2-e2es"},
}
html_last_updated_fmt = "%d/%m/%Y %H:%M"

# -- Mermaid ------------------------------------------------------------------
mermaid_version = "10.9.1"
mermaid_init_js = (
    "mermaid.initialize({startOnLoad:true,theme:'neutral',securityLevel:'loose',"
    "flowchart:{curve:'basis',useMaxWidth:true}});"
)
