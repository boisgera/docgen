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
import re
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
    iter = tree_iter
    def __repr__(self):
        typename = type(self).__name__
        args = ", ".join(repr(arg) for arg in self.args)
        return "{0}({1})".format(typename, args)
    def __json__(self):
        return {type(self).__name__: to_json(list(self.args))}

class Pandoc(PandocType):
    def __json__(self):
        meta, blocks = self.args[0], self.args[1]
        return [meta, [to_json(block) for block in blocks]]

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

def to_pandoc(json):
    def is_doc(item):
        return isinstance(item, list) and \
               len(item) == 2 and \
               isinstance(item[0], dict) and \
               "docTitle" in item[0].keys()
    if is_doc(json):
        return Pandoc(*[to_pandoc(item) for item in json])
    elif isinstance(json, list):
        return [to_pandoc(item) for item in json]
    elif isinstance(json, dict) and len(json) == 1:
        key, args = json.items()[0]
        pandoc_type = eval(key)
        return pandoc_type(*to_pandoc(args))
    else:
        return json
    
def to_json(doc_item):
    if hasattr(doc_item, "__json__"):
        return doc_item.__json__()
    elif isinstance(doc_item, list):
        return [to_json(item) for item in doc_item]
    else:
        return doc_item

def read(text):
    """
    Read a markdown text as a Pandoc instance.
    """
    json_text = str(pbs.pandoc(read="markdown", write="json", _in=text))
    json_ = json.loads(json_text)
    return to_pandoc(json_)

def write(doc):
    """
    Write a Pandoc instance as a markdown text.
    """
    json_text = json.dumps(to_json(doc))
    return str(pbs.pandoc(read="json", write="markdown", _in=json_text))

Pandoc.write = write
Pandoc.read = staticmethod(read)

#-------------------------------------------------------------------------------
# Pandoc Transforms
#-------------------------------------------------------------------------------

def apply(transform):
    def doc_transform(doc_item):
        for elt in doc_item.iter():
            transform(elt)
    return doc_transform

PandocType.apply = lambda doc_item, transform: apply(transform)(doc_item)
    

def increase_header_level(doc, delta=1):
    def _increase_header_level(delta):
        def _increase(doc_item):
            if isinstance(doc_item, Header):
                doc_item.args[0] = doc_item.args[0] + delta
        return _increase
    return doc.apply(_increase_header_level(delta))

def set_min_header_level(doc, minimum=1):
    levels = [item.args[0] for item in doc.iter() if isinstance(item, Header)]
    if not levels:
        return
    else:
        min_ = min(levels)
        if minimum > min_:
            delta = minimum - min_
            increase_header_level(doc, delta)

#-------------------------------------------------------------------------------

# TODO: hierarchical structure: class method docs should be browsed too.
#       return a list that contains [name, item, docstring, children] ?
#       add extra stuff such as line / file, source code, etc. ? Put this
#       stuff into an info dict ?

_targets = "module dict weakref doc builtins file name package"
_hidden_magic = ["__{0}__".format(name) for name in _targets.split()]

# TODO: normalize the docstrings wrt blank lines and spaces an initial 'tabs' ?
#       is pydoc already doing that ? Yes, via inspect it is (in inspect.getdoc).

# TODO: when found an external module, register somewhere (for the dependency
#       analysis ...)
# TODO: need to find the star-imports and for every object that has no
#       __module__, check that's there no such name in the star-imported
#       modules.
def object_tree(item, name=None, module=None, _cache=None):
    """
    Return the tree of items contained in item.

    The return value is a 3-uple (name, item, children).
    """
    if name is None:
        if hasattr(item, "__module__"):
            name = item.__module__ + "." + item.__name__
        else:
            name = item.__name__
    if module is None and isinstance(item, types.ModuleType):
        module = item

    tree = (name, item, [])
    if _cache is None:
        _cache = ([], [])
    if item not in _cache[0]:
        _cache[0].append(item)
        _cache[1].append(tree[2])
    if isinstance(item, types.ModuleType):
        children = inspect.getmembers(item)
    elif isinstance(item, type):
        children = item.__dict__.items() 
    else:
        children = []

    MethodWrapper = type((lambda: None).__call__)

    def is_local(item, name):
        if module:
            return getattr(_item, "__module__", module.__name__) == module.__name__
        else:
            return True

    for _name, _item in children:
        # exclude private and foreign objects as well as (sub)modules.
        # exclude __call__ for anything but classes (nah, detect wrapper instead)
        # some extra magic stuff should be excluded too (__class__, __base__, etc.)

        # OH, C'MON, even strings are a nested problem ! "a.__doc__.__doc__", etc ...

        if (not _name.startswith("_") or (_name.startswith("__") and _name.endswith("__") and not _name in _hidden_magic)) and \
           not isinstance(_item, types.ModuleType) and \
           is_local(item, name) and \
           not isinstance(_item, MethodWrapper):
           # import time; time.sleep(1.0)
           _name = name + "." + _name
           # print "*", _name, "|||",  _item, "|||", type(_item), "|||", isinstance(_item, types.ModuleType)
           if _item in _cache[0]:
               index = _cache[0].index(_item)
               new = (_name, _item, _cache[1][index])
           else:
               new = object_tree(_item, _name, module, _cache)
           tree[2].append(new)
    return tree



def doc_tree(tree):
    """
    Return a hierarchical structure with the docstrings of an object tree.

    (name, item, children) -> (name, docstring, children).

    The results are sorted according to the first line of the object def.
    """
    children = tree[2]
    children = sorted(children, key=lambda info: line(info[1]))
    _doc_trees = [doc_tree(child) for child in children]
    return (tree[0], inspect.getdoc(tree[1]) or "", _doc_trees)

# TODO: make rst input optional ? Or get rid of it for markdown ?

# TODO: implement a filter that will decrease the header level of rst stuff
#       by two.



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

def def_(name, item):
    try:
        return inspect.getsource(item).splitlines()[0].strip()
    except TypeError:
        return name + " (def. not available.)"

# TODO: check doctest management (sucks).

def line_number_finder(container):
    INF = 1e300000
    def line_number(info):
        qname, item, children = info
        name = qname.split(".")[-1]
        try:
            _line_number = inspect.getsourcelines(item)[1]
        except TypeError:
            try:
                source = inspect.getsource(container)
                pattern = r"\s*{0}\s*=".format(name)
                _line_number = 1
                for line in source.splitlines():
                    if re.match(pattern, line):
                        return _line_number
                    else:
                       _line_number += 1
                else:
                    _line_number = INF
            except TypeError:
                _line_number = INF
        return _line_number
    return line_number

def signature(function, name=None):
    argspec = inspect.getargspec(function)
    name = name or function.__name__
    nargs = len(argspec.args)
    args = ""
    defaults = argspec.defaults or []
    for i, arg in enumerate(argspec.args):
        try:
            default = defaults[i - nargs]
            args += "{0}={1!r}, ".format(arg, default)
        except IndexError:
            args += "{0}, ".format(arg)
    if argspec.varargs:
        args += "*{0}, ".format(argspec.varargs)
    if argspec.keywords:
        args += "**{0}, ".format(argspec.keywords) 
    if args:
        args = args[:-2]
    return name + "({0})".format(args)

def format(item, name=None, level=1, module=None):
    if module is None and isinstance(item, types.ModuleType):
        module = item
    name, item, children = object_tree(item, name)
    last_name = name.split(".")[-1]

    children = sorted(children, key=line_number_finder(item))

    markdown = "" 
    docstring = inspect.getdoc(item) or ""
    if isinstance(item, types.ModuleType):
        lines = docstring.splitlines()
        if lines:
            short = lines[0]
            long  = "".join(lines[1:]).strip()
        else:
            short = ""
            long  = ""
        markdown = level * "#" + " " + tt(name) + " -- " + short + "\n\n"
        markdown += long + "\n\n"
    elif isinstance(item, (types.FunctionType, types.MethodType)):
        markdown += level * "#" + " " + tt(signature(item))+ " [`function`]".format(signature(item))
        markdown += "\n\n"
        doc = Pandoc.read(docstring)
        set_min_header_level(doc, level + 1)
        docstring = doc.write()
        markdown += docstring + "\n\n"
    elif isinstance(item, type):
        markdown += level * "#" + " " + tt((last_name + "({0})").format(", ".join(t.__name__ for t in item.__bases__))) + " [`type`]"
        markdown += "\n\n"
        markdown += docstring + "\n\n"
    else: # "primitive" types
        # distinguish "constants" (with syntax __stuff__ or STUFF) from
        # variables ? Dunno ...
        markdown += level * "#" + " " + tt(last_name) + " [`{0}`]".format(type(item).__name__) + "\n\n"
        markdown += tt(repr(item)) + "\n\n"
        
    for name, item, _ in children:
        markdown += format(item, name=name, level=level+1) + "\n"
    return markdown

def main(module_name):
    module = importlib.import_module(module_name)
    return format(module)



def test():
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    module_name = sys.argv[1]
    print main(module_name)

