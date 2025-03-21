# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

import datetime
# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
import sys

sys.path.insert(0, os.path.abspath('..'))


def get_version():
    with open('../version.txt') as f:
        return f.read().strip()


# -- Project information -----------------------------------------------------

project = 'Colossal-AI'
copyright = f'{datetime.datetime.now().year}, HPC-AI Tech'
author = 'HPC-AI Technology Inc.'

# The full version, including alpha/beta/rc tags
release = get_version()

# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.mathjax',
    'sphinx.ext.napoleon',
    'myst_parser',
]

# Disable docstring inheritance
autodoc_inherit_docstrings = False

# Disable displaying type annotations, these can be very verbose
autodoc_typehints = 'none'

# Enable overriding of function signatures in the first line of the docstring.
autodoc_docstring_signature = True
autodoc_default_options = {'member-order': 'bysource'}

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = ['.build', 'Thumbs.db', '.DS_Store']

# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = 'sphinx_rtd_theme'
html_show_sourcelink = False
html_theme_options = {
    'navigation_depth': 2,
}

html_context = {
    'display_github': False,
    'github_user': 'hpcaitech',
    'github_repo': 'ColossalAI',
    #   'github_version': 'master/docs/',
}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']

html_css_files = [
    'css/rtd_theme.css',
]

# -- Extension configuration -------------------------------------------------
source_suffix = ['.rst', '.md', '.MD']
