#!/usr/bin/env python

"""
Generate LaTeX documentation from docstrings following Numpy/Scipy conventions.

Source: https://github.com/numpy/numpy/blob/master/doc/HOWTO_DOCUMENT.rst.txt
"""

# Python 2.7 Standard Library
import importlib
import inspect
import json
import pydoc
import sys
import types

# Third-Party Libraries
import pbs

#-------------------------------------------------------------------------------
# Sandbox: automatic generation of (typecked) classes.

#def typechecker(types_str):
#    types = [eval(_type) for _type in types_str.split()]
#    def typecheck(args):
#        if len(args) != len(types):
#            error = "invalid number of arguments against types pattern {0}"
#            raise TypeError(error.format(types_str))
#        for arg, _type in zip(args, type):
#            typecheck(arg, _type)
#    return typechecks

#def typecheck(item, pattern):
#    """
#    Typechecks items against a single type pattern.

#    The type pattern should be one of:

#      - a primitive or user-defined Python type,
#      - a `[type]` pattern 
#      - a `(type1, type2, ...)` pattern.
#    """
#    if isinstance(pattern, list):
#        if not isinstance(item, list):
#            raise TypeError() # TODO: error message
#        for _item in item:
#            typecheck(_item, pattern[0])
#    elif isinstance(pattern, tuple):
#        if not isinstance(item, tuple) or len(pattern) != len(item):
#            raise TypeError() # TODO: error message
#        for i, _item in enumerate(item):
#            typecheck(_item, pattern[i])
#    else:
#        if not isinstance(item, pattern):
#            error = "{0!r} is not of type {1}."
#            raise TypeError(error.format(item, pattern.__name__))

#def make_type(declaration): # such as "Block = BulletList [[Block]]"
#    # or "Block = DefinitionList [([Inline], [[Block]])]"	

#    parent, constructor = [item.strip() for item in declaration.split("=")]
#    items = constructor.split()
#    typename = items[0], items[1:]
#    _type = type(typename, (parent, ), {})
#    # TODO: install the type checker ...

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
        self.args = list(args)
    def __iter__(self):
        return iter(self.args)
    tree_iter = tree_iter
    def __repr__(self):
        typename = type(self).__name__
        args = ", ".join(repr(arg) for arg in self.args)
        return "{0}({1})".format(typename, args)
    def __json__(self):
        return {type(self).__name__: jsonify(list(self.args))}

class Pandoc(PandocType):
    def __json__(self):
        meta, blocks = self.args[0], self.args[1]
        return [meta, [jsonify(block) for block in blocks]]

class Block(PandocType):
    pass

class Header(Block):
    pass

class DefinitionList(Block):
    pass

class BulletList(Block):
    pass

class Plain(Block):
    pass

class BlockQuote(Block):
    pass

class RawBlock(Block):
    pass

class Inline(PandocType):
    pass

class Para(Inline):
    pass

class Code(Inline):
    pass

class Link(Inline):
    pass

class Str(Inline):
    def __init__(self, *args):
        self.args = [u"".join(args)]
    def __repr__(self):
        text = self.args[0]
        return "{0}({1!r})".format("Str", text)
    def __json__(self):
        return {"Str": self.args[0]}

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
    elif isinstance(item, dict) and len(item) == 1:
        key, args = item.items()[0]
        pandoc_type = eval(key)
        return pandoc_type(*objectify(args))
    else:
        return item
    

def jsonify(object):
    if hasattr(object, "__json__"):
        return object.__json__()
    elif isinstance(object, list):
        return [jsonify(item) for item in object]
    else:
        return object

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
    r = jsonify(o)
    print r
    print r == doc
#    print 79 *  "-"
#    for item in tree_iter(o):
#        print item
    
#-------------------------------------------------------------------------------

# TODO: hierarchical structure: class method docs should be browsed too.
#       return a list that contains [name, item, docstring, children] ?
#       add extra stuff such as line / file, source code, etc. ? Put this
#       stuff into an info dict ?

# TODO: normalize the docstrings wrt blank lines and spaces an initial 'tabs' ?
#       is pydoc already doing that ?

def get_docs(item, docs=None, context=None):
    "Get the docs !"
    docs = {item.__name__: {"item": item, "docstring": inspect.getdoc(item)}}
    item_name = item.__name__
    if context:
        item_name = context + "." + item_name
    is_module = type(item) == types.ModuleType
    for _name, _item in item.__dict__.items():
        try:
            if not _name.startswith("_") and \
               not is_module or _item.__module__ == item_name:
                docs[item_name + "." + _name] = \
                  {"item": _item, "docstring": inspect.getdoc(_item)}
        except (AttributeError, TypeError):
            pass
    def line(pair):
       info = pair[1]
       return inspect.getsourcelines(info["item"])[1]
    return sorted(docs.items(), key=line)

# TODO: make rst input optional ? Or get rid of it for markdown ?

# TODO: implement a filter that will decrease the header level of rst stuff
#       by two.

def patch_header(doc):
    for elt in tree_iter(doc):
        #print type(elt)
        if isinstance(elt, Header):
            #print elt
            elt.args[0] = elt.args[0] + 2
    return doc

def rst_to_md(text, *filters):
     doc = json.loads(str(pbs.pandoc(read="rst", write="json", _in=text)))
     doc = objectify(doc)
     for filter in filters:
         doc = filter(doc)
     doc = jsonify(doc)
     #print "***", doc
     return str(pbs.pandoc(read="json", write="markdown", _in=json.dumps(doc)))

def tt(x):
    return "`{0}`".format(x)

# TODO: improve def_: use the real name (multiple decl), for classes use
#       the constructor signature; get rid of the ":", use [class] or [function]
#       instead of the class or def keyword ? 

# TODO: Test support with cython ? That is, see what can be done WITHOUT the
#       inspect "getsource*" functions.

def def_(x):
    return inspect.getsource(x).splitlines()[0].strip()

# TODO: check doctest management (sucks).

def main(module_name):
    module = importlib.import_module(module_name)
    docs = get_docs(module).items()
    docs.sort(key = lambda item: item[1][2])
    markdown = ""
    name, (module, docstring, _) = docs[0]

    docstring = docstring.strip()
    short = docstring.splitlines()[0]
    long = "".join(docstring.splitlines()[1:]).strip()
    markdown = "# " + tt(name) + " -- " + short + "\n\n"
    markdown += rst_to_md(long)
    del docs[0]
    for name, (item, docstring, _) in docs:
        markdown += "\n## " + tt(def_(item)) + "\n\n" # use fct signature info.
        markdown += rst_to_md(docstring, patch_header)
    return markdown

def test():
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    #test_object_repr()
    module_name = sys.argv[1]
    print main(module_name)

