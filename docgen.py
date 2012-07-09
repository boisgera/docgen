#!/usr/bin/env python

"""
Generate LaTeX documentation from docstrings following Numpy/Scipy conventions.

Source: https://github.com/numpy/numpy/blob/master/doc/HOWTO_DOCUMENT.rst.txt
"""

# Python 2.7 Standard Library
import importlib
import json
import pydoc
import sys

# Third-Party Libraries
import pbs

def get_docs(module_name):
    module = importlib.import_module(module_name)
    docs = {}
    docs[module_name] = (module, pydoc.getdoc(module))
    for name, item in module.__dict__.items():
        try:
            if item.__module__ == module_name:
                docs[module_name + "." + name] = (item, pydoc.getdoc(item))
        except AttributeError:
            pass
    return docs

def iter(doc):
    # source: http://hackage.haskell.org/packages/archive/pandoc-types/1.9.1/doc/html/Text-Pandoc-Definition.html
    pass

def rst_to_md(text, **filters):
     doc = json.loads(str(pbs.pandoc(read="rst", write="json", _in=text)))
     print doc
     for filter in filters:
         doc = filter(doc)
     return str(pbs.pandoc(read="json", write="markdown", _in=json.dumps(doc)))

def main(module_name):
    docs = get_docs(module_name)
    latex_doc = ""
    module, doc = docs[module_name]
    latex_doc += rst_to_md(doc)
    del docs[module_name]
    for name, (item, doc) in docs.items():
        latex_doc += "\n" + name + "\n" # use fct signature info.
        latex_doc += rst_to_md(doc)

    return latex_doc

if __name__ == "__main__":
    module_name = sys.argv[1]
    print main(module_name)

