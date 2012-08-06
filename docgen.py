#!/usr/bin/env python

"""
Python documentation with Markdown

Given a Python module whose docstrings use the [Markdown syntax][markdown], 
print the full Markdown documentation with:

    $ docgen [MODULE-NAME]

This script depends on the Python 2.7 standard library as well as the
subprocess wrapper [`pbs`][pbs] and the [`pandoc`][pandoc] universal
document converter.

[markdown]: http://daringfireball.net/projects/markdown/syntax/
[pbs]: https://github.com/amoffat/pbs/
[pandoc]: http://johnmacfarlane.net/pandoc/
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
# Pandoc Document Model
#-------------------------------------------------------------------------------
def _tree_iter(item):
    "Tree iterator"
    yield item
    if not isinstance(item, basestring):
        try:
            it = iter(item)
            for subitem in it:
                for subsubitem in _tree_iter(subitem):
                    yield subsubitem
        except TypeError:
            pass

class PandocType(object):
    """
    Pandoc types base class

    Refer to the [Pandoc data structure definition](http://hackage.haskell.org/packages/archive/pandoc-types/1.8/doc/html/Text-Pandoc-Definition.html) (in Haskell) for details.
    """
    def __init__(self, *args):
        self.args = list(args)
    def __iter__(self):
        "Child iterator"
        return iter(self.args)
    def iter(self):
        "Tree iterator"
        return _tree_iter(self)
    def __json__(self):
        """
        Convert `self` into a Python object that may be encoded into text
        by `json.dumps`.
        """
        return {type(self).__name__: to_json(list(self.args))}
    def __repr__(self):
        typename = type(self).__name__
        args = ", ".join(repr(arg) for arg in self.args)
        return "{0}({1})".format(typename, args)

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

class CodeBlock(Block):
    pass

class BlockQuote(Block):
    pass

class RawBlock(Block):
    pass

class Inline(PandocType):
    pass

class Emph(Inline):
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

# TODO: insert HorizontalRule before every level 2 section. Unless I do that
#       at the LaTeX level ? Or don't do it generally, just before functions
#       and classes (no transform, do it directly during markdown generation) ?

#-------------------------------------------------------------------------------

# TODO: hierarchical structure: class method docs should be browsed too.
#       return a list that contains [name, item, docstring, children] ?
#       add extra stuff such as line / file, source code, etc. ? Put this
#       stuff into an info dict ?

_targets = "module dict weakref doc builtins file name package"
_hidden_magic = ["__{0}__".format(name) for name in _targets.split()]

def get_star_imports(module):
    try:
        source = inspect.getsource(module)
    except TypeError:
        source = ""
    pattern = r"\s*from\s*(\S*)\s*import\s*\*"
    lines = source.splitlines()
    modules = []
    for line in lines:
        match = re.match(pattern, line)
        if match:
            modules.append(match.groups()[0])
    return modules

def is_external(item, name, star_imports):
    last_name = name.split(".")[-1]
    if last_name.startswith("_") and not (last_name.startswith("__") and last_name.endswith("__")):
        return False
    for module_name in star_imports:
        module = importlib.import_module(module_name)
        if hasattr(module, last_name) and getattr(module, last_name) is item:
            return True
    else:
        return False

# TODO: when found an external module, register somewhere (for the dependency
#       analysis ...)
# TODO: need to find the star-imports and for every object that has no
#       __module__, check that's there no such name in the star-imported
#       modules.
def object_tree(item, name=None, module=None, _cache=None):
    """
    Return the tree of items contained in `item`.

    The return value is a `(name, item, children)` where `children`
    has the same structure.
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
    if id(item) not in [id(x) for x in _cache[0]]:
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

    star_imports = get_star_imports(module)

    for _name, _item in children:
        # exclude private and foreign objects as well as (sub)modules.
        # exclude __call__ for anything but classes (nah, detect wrapper instead)
        # some extra magic stuff should be excluded too (__class__, __base__, etc.)

        # OH, C'MON, even strings are a nested problem ! "a.__doc__.__doc__", etc ...

        if (not _name.startswith("_") or (_name.startswith("__") and _name.endswith("__") and not _name in _hidden_magic)) and \
           not isinstance(_item, types.ModuleType) and \
           is_local(item, name) and \
           not is_external(_item, _name, star_imports) and \
           not isinstance(_item, MethodWrapper):
           # import time; time.sleep(1.0)
           _name = name + "." + _name
           # print "*", _name, "|||",  _item, "|||", type(_item), "|||", isinstance(_item, types.ModuleType)

           # BUG: Numpy issue: when an array is "=="'d to SOME items (such as 
           #      a numeric value, a boolean, etc.), the result is an array.
           
           if id(_item) in [id(x) for x in _cache[0]]:
               index = [id(x) for x in _cache[0]].index(id(_item))
               new = (_name, _item, _cache[1][index])
           else:
               new = object_tree(_item, _name, module, _cache)
           tree[2].append(new)
    return tree

def tt(text):
    """
    Turn `text` into fixed-font text (or *teletype*).
    """
    return "`{0}`".format(text)

def line_number_finder(container):
    INF = 1e300000
    def line_number(info):
        qname, item, children = info
        name = qname.split(".")[-1]
        try:
            _line_number = inspect.getsourcelines(item)[1]
        except (IOError, TypeError):
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
            except (IOError, TypeError):
                _line_number = INF
        return _line_number
    return line_number

def signature(function, name=None):
    """
    Return the function signature as found in Python source:

        >>> def f(x, y=1, *args, **kwargs):
        ...     pass
        >>> print signature(f)
        f(x, y=1, *args, **kwargs)
        >>> print signature(f, name="g")
        g(x, y=1, *args, **kwargs)
    """
    argspec = inspect.getargspec(function)
    if name is None: 
        name = function.__name__
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

# TODO: reimplement getdoc with a variant on the stripping so that if tabs
#       /spaces are removed, the FIRST line shift (after BLANKLINE stripping) 
#       is also taken into account.
#       That convention would ease the formatting of doctests ...

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
            long  = "\n".join(lines[1:]).strip()
        else:
            short = ""
            long  = ""

        # TODO: make the distinction in short between titles (to be merged
        # in the title, that does not end with a "." and a short description,
        # that should not be merged (and ends with a ".").
        markdown = level * "#" + " " + tt(name) + " -- " + short + "\n\n"
        markdown += long + "\n\n"
    elif isinstance(item, (types.FunctionType, types.MethodType)):
        markdown += level * "#" + " " + tt(signature(item))+ " [`function`]".format(signature(item))
        markdown += "\n\n"
        doc = Pandoc.read(docstring)
        set_min_header_level(doc, level + 1)
        docstring = doc.write()
        markdown += docstring + "\n"
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
    # erf, does not work ???
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    module_name = sys.argv[1]
    print main(module_name)

