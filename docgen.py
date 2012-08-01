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

#-------------------------------------------------------------------------------
# Sandbox: automatic generation of (typecked) classes.

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
    # or "Block = DefinitionList [([Inline], [[Block]])]"	

    parent, constructor = [item.strip() for item in declaration.split("=")]
    items = constructor.split()
    typename = items[0], items[1:]
    _type = type(typename, (parent, ), {})
    # TODO: install the type checker ...

#-------------------------------------------------------------------------------
def tree_iter(item):
    yield item
    if not isinstance(item, basestring):
        try:
            it = iter(item)
            for subitem in it:
                for subsubitem in tree_iter(subitem):
                    yield subsubitem
        except TypeError:
            pass

class PandocType(object):
    def __init__(self, *args):
        self.args = args
    def __iter__(self):
        return iter(self.args)
    tree_iter = tree_iter
    def __repr__(self):
        typename = type(self).__name__
        args = ", ".join(repr(arg) for arg in self.args)
        return "{0}({1})".format(typename, args)

class Pandoc(PandocType):
    def __init__(self, *args):
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

class RawBlock(Block):
    pass

class Inline(PandocType):
    pass

class Para(Inline):
    pass

class Link(Inline):
    pass

class Str(Inline):
    def __init__(self, *args):
        self.args = [u"".join(args)]
    def __repr__(self):
        text = self.args[0]
        return "{0}({1!r})".format("Str", text)

# Rk: `Space` is encoded as a string in exported json. 
# That's kind of a problem because we won't typematch it like the other
# instances and searching for the string "Space" may lead to false positive.
# The only way to deal with it is to be aware of the context where the Space
# atom (inline) may appear but here we typically are not aware of that.

class Strong(Inline):
    pass

class Math(Inline):
    pass

def objectify(item, **kwargs):
    if kwargs.get("toplevel"):
        doc = item
        return Pandoc(*doc)

    if isinstance(item, list):
        items = item
        return [objectify(item) for item in items]
    elif isinstance(item, (basestring, int)):
        return item
    else: # dict with a single entry.
        assert isinstance(item, dict) and len(item) == 1
        key, args = item.items()[0]
        pandoc_type = eval(key)
        return pandoc_type(*objectify(args)) 

src = r"""
UUUUu
------

Jdshjsdhshdjs **bold** neh.

  - kdsldks,
  - djskdjskdjskdjs,
  - dkk.

Let's try some LaTeX: $a=1$.

  $$
  \int_0^2 f(x) \, dx
  $$

  \begin{equation}
  a = 2
  \end{equation}

Get some [links](http://www.dude.com "wooz") --. Can I get more ?

"""

def test_object_repr():
    doc = json.loads(str(pbs.pandoc(read="markdown", write="json", _in=src)))
    print doc
    o = objectify(doc, toplevel=True)
    print o
    print 79 *  "-"
    for item in tree_iter(o):
        print item
    
#-------------------------------------------------------------------------------

def get_docs(module):
    """
    Get a module docstrings as a qualified name to (item, docstring) mapping.
    """
    if isinstance(module, basestring):
        module_name = module
        module = importlib.import_module(module)
    else:
        module_name = module.__name__

    docs = {module_name: (module, pydoc.getdoc(module))}
    for name, item in module.__dict__.items():
        try:
            if item.__module__ == module_name:
                docs[module_name + "." + name] = (item, pydoc.getdoc(item))
        except AttributeError:
            pass
    return docs

# TODO: generate a hierarchy of classes from the Pandoc document model.
#       each class implements `__iter__` (and what else ? etree-like model ?).


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

