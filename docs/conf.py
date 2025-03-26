# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import os
import sys

sys.path.insert(0, os.path.abspath("../"))
sys.path.insert(0, os.path.abspath("_themes"))

project = "NfoForge"
copyright = "2025, jesterr0"
author = "jesterr0"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.napoleon"
]

always_use_bars_union = True
add_module_names = False
autodoc_typehints_format = "short"
python_use_unqualified_type_names = True
python_use_unqualified_names = True
typehints_fully_qualified = False
typehints_use_signature = False
typehints_use_signature_return = True
typehints_document_rtype = True

source_suffix = ".rst"

master_doc = "index"

templates_path = ["_templates"]

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]


# The name of the Pygments (syntax highlighting) style to use.
pygments_style = "flask_theme_support.FlaskyStyle"

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "furo"
html_static_path = ["_static"]
