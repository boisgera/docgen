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

def typechecker(types_str):
    types = [eval(_type) for _type in types_str.split()]
    def typecheck(args):
        if len(args) != len(types):
            error = "invalid number of arguments against types pattern {0}"
            raise TypeError(error.format(types_str))
        for arg, _type in zip(args, type):
            typecheck(arg, _type)
    return typechecks

def typecheck(item, pattern):
    """
    Typechecks items against a single type pattern.

    The type pattern should be one of:

      - a primitive or user-defined Python type,
      - a `[type]` pattern 
      - a `(type1, type2, ...)` pattern.
    """
    if isinstance(pattern, list):
        if not isinstance(item, list):
            raise TypeError() # TODO: error message
        for _item in item:
            typecheck(_item, pattern[0])
    elif isinstance(pattern, tuple):
        if not isinstance(item, tuple) or len(pattern) != len(item):
            raise TypeError() # TODO: error message
        for i, _item in enumerate(item):
            typecheck(_item, pattern[i])
    else:
        if not isinstance(item, pattern):
            error = "{0!r} is not of type {1}."
            raise TypeError(error.format(item, pattern.__name__))

def make_type(declaration): # such as "Block = BulletList [[Block]]"
    parent, constructor = [item.strip() for item in declaration.split("=")]
    items = constructor.split()
    typename = items[0], items[1:]
    _type = type(typename, (parent, ), {})
    # TODO: install the type checker ...

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

def test():
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    test_object_repr()
    #module_name = sys.argv[1]
    #print main(module_name)

