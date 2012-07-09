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

class PandocType(object):
    def __init__(self, *args):
        self.args = objectify(list(args))
    def __iter__(self):
        return iter(args)
    def __repr__(self):
        typename = type(self).__name__
        args = ", ".join(repr(arg) for arg in self.args)
        return "{0}({1})".format(typename, args)

def typecheck(item, type_):
    # handle str, [types], (type1, type2, ...), that's about it.
    pass


def make_type(declaration): # such as "Block = BulletList [[Block]]"
    parent, signature = [item.strip for item in declaration.split("=")]
    items = signature.split()
    typename = items[0]
    

class Pandoc(PandocType):
    def __init__(self, *args):
        print "***", args
        meta = args[0]
        blocks = objectify(args[1])
        self.args = [meta, blocks]

class Block(PandocType):
    pass

class Header(Block):
    pass

class BulletList(Block):
    pass

class Plain(Block):
    pass

class Inline(PandocType):
    pass

class Para(Inline):
    pass

class Str(Inline):
    pass

# don't ? use the string as an atom ?
class Space(Inline):
    pass

def objectify(*items, **kwargs):
    objects = []
    if kwargs.get("toplevel"):
        assert len(items) == 1
        doc = items[0]
        return Pandoc(*doc)
    for item in items:
        if isinstance(item, list):
            items = item
            objects.append([objectify(item) for item in items])
        elif isinstance(item, (basestring, int)):
            return item
        else:
            key, value = item.items()[0]
            pandoc_type = eval(key)
            return pandoc_type(*value) 
    return objects

src = """
UUUUu
------

Jdshjsdhshdjs

  - lskdsl
  - djskdjs kdj sk
  - dlskdlskdlskdlsk
    kdslkdlsdksdksl
    ldksldksld

"""

def test_object_repr():
    doc = json.loads(str(pbs.pandoc(read="markdown", write="json", _in=src)))
    print doc
    print objectify(doc, toplevel=True)
    
#-------------------------------------------------------------------------------

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

# TODO: generate a hierarchy of classes from the Pandoc document model.
#       each class implements `__iter__` (and what else ? etree-like model ?).

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
    test_object_repr()
    #module_name = sys.argv[1]
    #print main(module_name)

