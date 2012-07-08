#!/usr/bin/env python

"""
LaTeX documentation from docstrings following Numpy/Scipy conventions.

Source: https://github.com/numpy/numpy/blob/master/doc/HOWTO_DOCUMENT.rst.txt
"""

# Python 2.7 Standard Library
import importlib
import sys

def main(name):
    docs = {}
    module = importlib.load_module()
    docs[module] = module.__doc__
    for item in module.__dict__:
        try:
            doc = item.__doc__
            if item.__module__ == name:
                docs[item] = doc
        except AttributeError:
            pass

if __name__ == "__main__":
    name = sys.argv[1]
    # main(name)
    print "***", name, "***"

