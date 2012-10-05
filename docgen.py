#!/usr/bin/env python
# encoding: utf-8
"""
Python documentation with Markdown

Given a Python module whose docstrings use the [Markdown syntax][markdown], 
print the full Markdown documentation with:

    $ docgen [MODULE-NAME]

This script depends on the Python 2.7 standard library as well as the
subprocess wrapper [`sh`][sh] and the [`pandoc`][pandoc] universal
document converter.

[markdown]: http://daringfireball.net/projects/markdown/syntax/
[sh]: https://github.com/amoffat/sh
[pandoc]: http://johnmacfarlane.net/pandoc/
"""

# Python 2.7 Standard Library
import copy
import importlib
import inspect
import json
import os
import pydoc
import re
import shutil
import sys
import tempfile
import types

# Third-Party Libraries
import script
import sh

#
# Metadata 
# ------------------------------------------------------------------------------
#

__author__ = u"Sébastien Boisgérault <Sebastien.Boisgerault@mines-paristech.fr>"
__license__ = "MIT License"
__version__ = None

#
# Pandoc Document Model
# ------------------------------------------------------------------------------
#
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
    def apply(self, transform): 
        apply(transform)(self)
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
    @staticmethod 
    def read(text):
        return read(text)
    def write(self):
        return write(self)

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

#
# **Remark:** `Space` is encoded as a string in exported json. 
# That's kind of a problem because we won't typematch it like the other
# instances and searching for the string "Space" may lead to false positive.
# The only way to deal with it is to be aware of the context where the Space
# atom (inline) may appear but here we typically are not aware of that.
#

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
    json_text = str(sh.pandoc(read="markdown", write="json", _in=text))
    json_ = json.loads(json_text)
    return to_pandoc(json_)

def write(doc):
    """
    Write a Pandoc instance as a markdown text.
    """
    json_text = json.dumps(to_json(doc))
    return str(sh.pandoc(read="json", write="markdown", _in=json_text))

#
# Pandoc Transforms
# ------------------------------------------------------------------------------
#
def apply(transform):
    def doc_transform(doc_item):
        for elt in doc_item.iter():
            transform(elt)
    return doc_transform


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

#
# TODO 
#   : insert HorizontalRule before every level 2 section. Unless I do that
#     at the LaTeX level ? Or don't do it generally, just before functions
#     and classes (no transform, do it directly during markdown generation) ?
#

#
# ------------------------------------------------------------------------------
#

#
# TODO
#   : hierarchical structure: class method docs should be browsed too.
#     return a list that contains [name, item, docstring, children] ?
#     add extra stuff such as line / file, source code, etc. ? Put this
#     stuff into an info dict ?
#
_targets = "module dict weakref doc builtins file name package"
_hidden_magic = ["__{0}__".format(name) for name in _targets.split()]

def get_star_imports(module):
    try:
        source = inspect.getsource(module)
    except TypeError:
        source = ""
    pattern = r"\s*from\s*(\S*)\s*import\s*\*"
    lines = source.split("\n")
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

# TODO
#   : when found an external module, register somewhere (for the dependency
#     analysis ...)
# TODO
#   : need to find the star-imports and for every object that has no
#     `__module__`, check that's there no such name in the star-imported
#     modules.
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

INF = 1e300000

def line_number_finder(container):
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
                for line in source.split("\n"):
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

# Having issue with signature when the function is a built-in ...
# need to fallback on source syntax analysis. (TODO).
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

def _get_comments(module):
    comments = []
    try:
        source = inspect.getsource(module)
    except IOError:
        return comment
    pattern = "^#\s*\n(# [^\n]*\n)*#\s*\n"
    for match in re.finditer(pattern, source, re.MULTILINE):
        line_number = source.count("\n", 0, match.start()) + 1
        comment = match.group(0)
        comment = "\n".join(line[2:] for line in comment.split("\n"))
        comments.append((line_number, comment))
    return comments
       
def last_header_level(markdown):
    doc = Pandoc.read(markdown)
    levels = [item.args[0] for item in doc.iter() if isinstance(item, Header)]
    if levels:
        return levels[-1]

#
# Source Declaration Analysis
# ------------------------------------------------------------------------------
#

# TODO: take source as an argument, create a list of "objects" with names
#       and other info such as type, plus some type-specific info and
#       chidren. Add some sources / lineno info into the mix so that the
#       original source can be reconstructed easily.
#       How to deal with indentation and blanklines ? Factor indentation 
#       when we can ? How do we deal with line continuations ?

# TODO: start with the generation of a stream of (types, with data) events
#       that all have a lineno, THEN create the appropriate structure ? Use
#       a state when doing so that to begin with, has a stack of all indents ?
#       Have a INDENT, DEINDENT (?). START_DECL, END_DECL, START/END-COMMENT,
#       same for docstrings, etc. etc.

def is_blank(line):
    whitespace = "\s*"
    return re.match(whitespace, line).group(0) == line

class Locator(object):
    def __init__(self, text):
        self._offsets = [0]
        for line in text.split("\n"):
            self._offsets.append(self._offsets[-1] + len(line) + 1)

    def lineno(self, offset):
        "Return lineno - 1 and the relative offset"
        for i, _offset in enumerate(self._offsets):
            if offset < _offset:
                return (i - 1, offset - self._offsets[i-1])

    def offset(self, lineno, offset):
         return sum([len for len in self._offsets[:lineno]] + [offset], 0)

# Q: should finder be named ? 
# TODO: Finder composer (based on first match).

# Finder have name AND return their name ???
# register all finders globally ? Don't ?

def finder(name, pattern=None, *flags):
    if pattern is None:
        pattern = "({0})".format(re.escape(name))
    pattern = re.compile(pattern, *flags)
    def find(text, start=0):
        match = pattern.search(text, start)
        if match is None:
            return None
        else:
            start, end = match.span(1)
            return name, start, end
    find.name = name
    return find


def first_then_longest(item):
    return item[1], -item[2]


def scan1(text):
    finders  = []
    finders += [finder(symbol) for symbol in "( [ { ) ] }".split()]
    finders += [finder("BLANKLINE", r"(^[ \t\r\f\v]*\n)", re.MULTILINE)]
    finders += [finder("COMMENT"  , r"([ \t\r\f\v]*#.*\n?(?:[ \t\r\f\v]*#.*\n?)*)")]
    finders += [finder("LINECONT" , r"(\\\n)")]
    finders += [finder("STRING"   , r'("(?:[^"]|\\")*")')]
    finders += [finder("STRING"   , r'("""(?:[^"]|\\"|"{1,2}(?!"))*""")')]
    finders += [finder("STRING"   , r"('(?: [^']|\\')*')")]
    finders += [finder("STRING"   , r"('''(?:[^']|\\'|'{1,2}(?!'))*''')")]

    start = 0
    while start < len(text):
        results = []
        for find in finders:
            result = find(text, start)
            if result is not None:
                results.append(result)
        if results:
            results.sort(key=first_then_longest)
            result = results[0]
            yield result
            start = result[2]
        else:
            break

def scan2(text):
    match = {"(": ")", "[": "]", "{": "}", ")": "(", "]": "[", "}": "{"}
    waitfor = []

    for name, start, end in scan1(text):
        if name in ["(", "[", "{"]:
            waitfor.append((match[name], start))
        elif waitfor and name == waitfor[-1][0]:
            _, start = waitfor.pop()
            yield match[name] + name, start, end
        else:
            yield name, start, end

def scan3(text):
    output = list(scan2(text))
    output.sort(key=first_then_longest)
    return output

def skip_lines(text):
    lines = []
    locator = Locator(text)
    for name, start, end in scan3(text):
        start, end = locator.lineno(start), locator.lineno(end)
        if name == "BLANKLINE":
            lines.append(start[0])
        if name == "COMMENT":
            start_line = start[0] + (start[1] != 0)
            end_line = end[0] - 1
            lines += [line for line in range(start_line, end_line + 1)]
        if name == "LINECONT":
            lines.append(start[0] + 1)
        if name in "() [] {} STRING".split():
            start_line = start[0] + 1
            end_line = end[0]
            lines += [line for line in range(start_line, end_line + 1)]
    return set(lines)

def get_lines(source, lineno):
    pass

def tab_match(line, tabs):
    pattern = re.compile("^[ \t\r\f\v]+", re.MULTILINE)
    _tabs = tabs[:]
    matched = []

    while _tabs:
        tab = _tabs.pop(0)
        if line.startswith(tab):
            matched.append(tab)
            line = line[len(tab):]
        else:
            break

    match = pattern.search(line)
    if match:
        extra = match.group(0)
    else:
        extra = None

    if matched == tabs or not extra:
        return matched, extra
    else:
        raise ValueError("indentation error")

def indents(source):
    """
    Return a sequence of `(lineno, tabs)`
    """
    skip = skip_lines(source)
    tabs = []
    pattern = re.compile("^[ \t\r\f\v]+", re.MULTILINE)
    for i, line in enumerate(source.split("\n")):
        if i not in skip:
            match, extra = tab_match(line, tabs)
            if extra:
                yield i, +1
                tabs.append(extra)
            else:
                yield i, len(match) - len(tabs)
                tabs = tabs[:len(match)]

def parse_declaration(line):
    finders  = []
    finders += [finder("function"  , r"^\s*c?p?def\s+([_0-9a-zA-Z]+)\s*\(")]
    finders += [finder("assignment", r"^\s*([_0-9a-zA-Z]+)\s*=\s*")]
    finders += [finder("class"     , r"^\s*class\s+([_0-9a-zA-Z]+)\s*\(")]
    results, result = [], None
    for find in finders:
        result = find(line)
        if result is not None:
            results.append(result)
    if results:
        results.sort(key=first_then_longest)
        result = results[0]
        result = result[0], line[result[1]:result[2]]
        return result
    else:
        return None, None

# ------------------------------------------------------------------------------
# TODO: tree (or make_tree) function that produces a [lineno, info, children]
#       (or even [info, children] ?) hierarchical structure. All the relevant
#       information (type, name, etc.) is stored in the struct info. Later
#       -- beyond syntax analysis -- introspection-based information can be
#       added to the info object, such as the object itself, the docstring,
#       etc. The special markdown comments should also be intertwined.
#       In info, use None (for lineno, name, type when it is required.)
#       
# Q: how should line continuations be handled ? In a first approach,
#    we don't do anything but later, maybe the lineno should be 
#    replaced with a RANGE of lineno ? 



class Info(object):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
    def __repr__(self):
        return "Info(**{0})".format(self.__dict__)
    __str__ = __repr__


# How to handle line cont ? Markdown comments and more generally multiple
# line stuff ? replace lineno with a range ? start and end lineno + offset ?
# OR (simpler): create a lineno -> lines function and use it :) (instead of
# the skipping mecanism). Arf, not that simple ... Instead an iterator that
# returns (lineno, lines) ? But to work without a major redesign, the lineno
# would have to return something that is subject to tab analysis ... (that
# does not suspend the identation state). And that cannot always be done,
# YES IT CAN BE DONE
# if the file start with comments for example. ... BULL ! Just attribute
# this chunk to the module itself.


# TODO: insert markdown comments at this level ?

# TODO: lookahead for the next lineno: the missing lines in the iteration 
#       should be stacked and added to the node info.
#      

# TODO: check that all blanklines are here.
def make_tree(source):
    lines = source.split("\n")
    items = [(Info(lineno=0, name=None, type=None), [])]
    item = items[0]
    prev_lineno = 0
    def push(item):
        items.append(item)
    def fold():
        item = items.pop()
        items[-1][-1].append(item)
    for lineno, tab in indents(source):
        source = "\n".join(lines[prev_lineno:lineno])
        item[0].source = source
        type, name = parse_declaration(lines[lineno])
        if tab <= 0 and len(items) >= 2:
            for _ in range(-tab+1):
                fold()
        info = Info(lineno=lineno, name=name, type=type)
        item = (info, [])
        push(item)
        prev_lineno = lineno
    else:
        lineno = len(lines)
        source = "\n".join(lines[prev_lineno:lineno]) # no trailing newline.
        # splitlines does not honor it anyway. BITCH !. Use split("\n") instead.
        item[0].source = source
    while len(items) >= 2:
        fold()
    return items[0]

# TODO: restore the BLANKLINEs ?
def display_tree(tree, nest=""):
    template = "{info.lineno:>5} {nest:>9} | {info.name:>15} {object_type:>12} {info.type:>12}"
    try:
        object = getattr(tree[0], "object")
        object_type = type(object).__name__
    except AttributeError:
        object_type = None  
    left = template.format(info=tree[0], nest=nest, object_type=object_type)
    lines = tree[0].source.split("\n") 
    if lines:
        print left, "|", lines[0]
        for line in lines[1:]:
            print len(left) * " ", "|", line
    children = tree[1]
    for child in children:
        display_tree(child, nest=nest+"+")

# ------------------------------------------------------------------------------

def get_declarations(tree, decls=None, ns=None):
    if decls is None:
        decls = []
    line, name, type, children = tree

    if type != "unknown":
        qname = (ns + "." if ns else "") + name
        decls.append((line, qname, type))
        if type in ("class", "module"):
            for child in children:
                get_declarations(child, decls, qname)
    return decls


def _format(item, decls, name=None, level=1, module=None, comments=None):
    if module is None and isinstance(item, types.ModuleType):
        module = item
    if comments is None:
        comments = get_comments(module)
    name, item, children = object_tree(item, name)
    last_name = name.split(".")[-1]

    markdown = ""
    children = sorted(children, key=line_number_finder(item))


    docstring = inspect.getdoc(item) or ""
    if isinstance(item, types.ModuleType):
        lines = docstring.split("\n")
        if lines:
            short = lines[0] # TODO: what if there is no short desc. ?
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
        if isinstance(item, unicode):
            string = item.encode("utf-8")
        else:
            string = str(item)
        markdown += tt(string) + "\n\n"
        

    for name, item, _children in children:
        line_number = line_number_finder(module)((name, item, _children))
        _comments = copy.copy(comments)
        text, last_level = format_comments(comments, up_to=line_number)
#        print ">>> " + name + " " + 60 * ">"
#        print line_number
#        print _comments
#        print text
#        print 79 * "<"
      
        markdown += text
        if last_level:
            level = last_level
        markdown += format(item, name, level+1, module, comments) + "\n"
    return markdown


def get_comments(source):
    comments = []
    pattern = "^#\s*\n(# [^\n]*\n)*#\s*\n"
    for match in re.finditer(pattern, source, re.MULTILINE):
        line_number = source.count("\n", 0, match.start())
        comment = match.group(0)
        comment = "\n".join(line[2:] for line in comment.split("\n")[1:])
        comments.append((line_number, comment))
    return comments

_formatters = []


def format(tree, state):
    _match = False
    for types, formatter in _formatters:
        if not types:
            _match = True
        else:
            try:
                object = tree[0].object
                _match = any(isinstance(object, type) for type in types)
            except AttributeError:
                pass
        if _match:
            state["restore"] = True
            return formatter(tree, state)

def formatter(*types):
    def register(formatter):
        _formatters.append((types, formatter))
        return formatter
    return register

@formatter(types.FunctionType, types.MethodType, types.BuiltinFunctionType)
def format_function(tree, state):
    object = tree[0].object
    markdown  = state["level"] * "#" + " " 
    markdown += tt(signature(object))+ " [`function`]\n"
    markdown += "\n"
    docstring = inspect.getdoc(object) or ""
    if docstring:
        doc = Pandoc.read(docstring)
        set_min_header_level(doc, state["level"] + 1)
        docstring = doc.write()
        markdown += docstring + "\n"
    level = state["level"]
    state["level"] = level + 1
    for child in tree[1]:
        markdown += format(child, state)
    if state["restore"]:
        state["level"] = level
    return markdown

# TODO: recursivity. Beware: the comments should be 
# intertwined. The most basic solution would duplicate
# the comment management code. Can we do better ?
@formatter(type)
def format_type(tree, state):
    object = tree[0].object
    name = tree[0].name
    markdown  = state["level"] * "#" + " "
    bases_names = [type.__name__ for type in object.__bases__] 
    markdown += tt((name + "({0})").format(", ".join(bases_names))) 
    markdown += " [`type`]\n"
    markdown += "\n"
    docstring = inspect.getdoc(object) or ""
    if docstring:
        markdown += docstring + "\n\n"
    level = state["level"]
    state["level"] = level + 1
    for child in tree[1]:
        markdown += format(child, state)
    if state["restore"]:
        state["level"] = level
    return markdown

# This is ugly. Create an object loader ? with a LoadError ?
class Objects(object):
    def __getitem__(self, qname):
        parts = qname.split(".")
        object = None
        base = ""
        while parts:
            part = parts.pop(0)
            base = (base + "." if base else "") + part
            try: 
                object = importlib.import_module(base)
            except ImportError:
                parts.insert(0, part)
                break
        if object is None:
           raise KeyError
        for part in parts:
           try:
               object = getattr(object, part)
           except AttributeError:
               raise KeyError
        return object

objects = Objects()

def objectify(tree, ns=""):
    name = tree[0].name
    if name:
        qname = (ns + "." if ns else "") + name
        # print "qname", qname
        try:
            tree[0].object = objects[qname]
        except KeyError:
            pass
        for child in tree[1]:
            objectify(child, ns=qname)

class Markdown(object):
    def __init__(self, markdown):
        self.markdown = markdown
    def __str__(self):
        return self.markdown
    @staticmethod
    def from_comment(comment):
        #print "***", repr(comment)
        # TODO: include the syntax check ?
        lines = comment.split("\n")
        lines = [line[2:] for line in lines[1:-1]]
        return Markdown("\n".join(lines) + "\n")

@formatter(Markdown)
def format_markdown(tree, state):
    object = tree[0].object
    markdown = str(object)

    #print "***", markdown

    doc = Pandoc.read(markdown)
    levels = [item.args[0] for item in doc.iter() if isinstance(item, Header)]
    if levels:
        state["level"] = levels[-1] + 1
        state["restore"] = False # disable the parent(s) level restore.
    # BUG: won't work in this models as the formatters spawn a new *copy* of
    #      the state for every children and the comments appear for now as
    #      SONS of existing elements when the role we give them here is the
    #      opposite (parents). This is quite a mess, even a change from son
    #      to sibling (a pain in the ass but it should probably be done as
    #      the mental model is simpler) won't be enough. So we have to make
    #      this change AND replace the state copy replaces with a share/restore
    #      feat. ? Study how this option would interact with comments (not very
    #      well AFAICT).
    return markdown

@formatter(object)
def format_object(tree, state):
    object = tree[0].object
    name = tree[0].name
    markdown  = state["level"] * "#" + " " + tt(name) 
    markdown += " [`{0}`] \n".format(type(object).__name__)
    markdown += "\n"
    if isinstance(object, unicode):
        string = object.encode("utf-8")
    else:
        string = str(object)
    markdown += tt(string) + "\n\n"
    level = state["level"]
    state["level"] = level + 1
    for child in tree[1]:
        markdown += format(child, state)
    if state["restore"]:
        state["level"] = level
    return markdown

@formatter()
def format_default(tree, state):
    markdown = ""
    level = state["level"]
    state["level"] = level + 1
    for child in tree[1]:
        markdown += format(child, state)
    if state["restore"]:
        state["level"] = level
    return markdown

def depth(tree):
    if not tree[1]:
       return 1
    else:
       return 1 + max(depth(child) for child in tree[1])

# We can't do it like that ... the comment would have to be added AFTER the
# component not under it ... and then the issue is that the comment is nested
# with the same level as the component and the display loop may not go deep
# enough to handle it. Arf, this is the issue with the "intertwined" model ...


# BUG: the match of the comment (or the restructuration ?) may omit characters.
#      That's probably because if the special comments ENDS the source, there is
#      no trailing newline.
def commentify(tree):
    source = getattr(tree[0], "source", None)
    object = getattr(tree[0], "object", None)
    if source is not None and (object is None or not isinstance(object, Markdown)):
        pattern = r"^#\s*\n(?:# [^\n]*\n)*#\s*(\n|$)"
        matches = list(re.finditer(pattern, source, re.MULTILINE))
        #print source
        for i, match in enumerate(matches):
            start = match.start()
            end = match.end()
#            print "***"
#            #print repr(source)
#            print repr(source[match.start():match.end()])
#            print "***"
            #start = source.count("\n", 0, match.start())
            #end   = source.count("\n", 0, match.end())
            if i == 0:
                tree[0].source = source[:start]#"\n".join(source.split("\n")[:start])
            if i+1 < len(matches):
                next = matches[i+1].start() #source.count("\n", 0, matches[i+1].start())
            else:
                next = len(source) # len(source.split("\n"))
            comment = Markdown.from_comment(source[start:end])
            # Markdown.from_comment("\n".join(source.split("\n")[start:end]))
            line_start = source.count("\n", 0, start)
            info = Info(name=None, lineno=tree[0].lineno + line_start, object=comment, type=None)
            info.source = source[start:next]#"\n".join(source.split("\n")[start:next])
            tree[1].insert(i, (info, []))

    for child in tree[1]:
        commentify(child)


#if __name__ == "__main__":
#    source = open(sys.argv[1]).read()
#    tree = make_tree(source)
#    objectify(tree)
#    commentify(tree)


class Undefined(object):
    def __repr__(self):
        return "undefined"
    __str__ = __repr__

undefined = Undefined()

def docgen(module, source):
    module_name = module.__name__
    tree = make_tree(source)
    tree[0].name = module_name
    objectify(tree)

    #print depth(tree)    

    commentify(tree)

#    display_tree(tree)
#    print 5*"\n"

    level = 1
    markdown = ""

    docstring = inspect.getdoc(module) or ""
    doclines = docstring.split("\n")
    if len(doclines) == 1:
        short, long = doclines[0].strip(), ""
    elif len(doclines) >= 2 and not doclines[1].strip():
        short, long = doclines[0].strip(), "\n".join(doclines[2:])
    else:
        short, long = "\n".join(doclines)

    # comments = get_comments(source)

    # Rk: we could make the distinction in short between titles (to be merged
    # in the title, that does not end with a "." and a short description,
    # that should not be merged (and ends with a ".").

    # TODO: refactor into `format_module`.
    markdown  = "#" + " " + tt(module_name)
    markdown += (" -- " + short + "\n\n") if short else "\n\n"
    markdown += long + "\n\n" if long else ""

    state = {"level": level, "namespace": module_name, "restore": True}

    for child in tree[1]:
        markdown += format(child, state)

    return markdown

## Arguments: module name, optionally corresponding file.
#def _main(filename):# temp, testing purpose.
#    src = open(filename).read()
#    lines = src.split("\n")
#    module_name = os.path.basename(filename).split(".")[0]
#    t = scope_tree(src, module_name)
#    decls = get_declarations(t)
#    for line, name, type in decls:
#        print "{0:>5} | {1:>30}, {2}".format(line, name, type)
#    print


#def tree(source, indent=None):
#    if isinstance(source, basestring):
#        source = source.split("\n")
#    if indent is None:
#        indent = []
#    root = []
#    def indents(line):
#        if is_blank(line):
#            return 0
#        if not line.startswith(indent):
#            return -1
#        if line.startswith(indent) and line[len(indent):].startswith(" "):
#            return +1
#        else:
#            return 0
#    while source:
#        line = source.pop(0)
#        d = delta(line)
#        print d, line
#        if d == 0:
#            root.append(line)
#        elif d < 0:
#            return root
#        else:
#            _indent = re.match("\s*", line).group(0)
#            sub = [line, tree(source, indent=_indent)]
#            root.append(sub)
#    return root
    

def get_decl(line):
    """
    Return `(name, type)`
    """
    function = r"(?:c?p?def)\s+(?P<name>[_0-9a-zA-Z]+)\("
    type = r"(class)\s+(?P<name>[_0-9a-zA-Z]+)("
    assign = r"(?P<name>[_0-9a-zA-Z]+)\s*\+?="

#
# ------------------------------------------------------------------------------
#

# BUG: any item with `inf` as a line_number (meaning unknown line number,
#      flush to the end will flush out ALL of the source comments, including
#      those out of the class declaration for example. 
#      If we could reduce the unknown decl line numbers to 0 that would be 
#      extra nice ... Do our best and otherwise EXCLUDE the objects whose
#      line number is unknown ?
#      Base the improvement on source analysis (with re), something that could
#      be working on cython too ?
def format_comments(comments, up_to=INF):
    markdown = ""
    level = None
    while True:
        try:
            line_number, comment = comments.pop(0)
            if line_number > up_to:
                comments.insert(0, (line_number, comment))
                break
            else:
                markdown += comment
        except IndexError:
            break
    if markdown:
        return markdown, last_header_level(markdown)
    else:
        return "", None
     

def _format(item, name=None, level=1, module=None, comments=None):
    if module is None and isinstance(item, types.ModuleType):
        module = item
    if comments is None:
        comments = get_comments(module)
    name, item, children = object_tree(item, name)
    last_name = name.split(".")[-1]

    markdown = ""
    children = sorted(children, key=line_number_finder(item))


    docstring = inspect.getdoc(item) or ""
    if isinstance(item, types.ModuleType):
        lines = docstring.split("\n")
        if lines:
            short = lines[0] # TODO: what if there is no short desc. ?
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
        if isinstance(item, unicode):
            string = item.encode("utf-8")
        else:
            string = str(item)
        markdown += tt(string) + "\n\n"
        

    for name, item, _children in children:
        line_number = line_number_finder(module)((name, item, _children))
        _comments = copy.copy(comments)
        text, last_level = format_comments(comments, up_to=line_number)
#        print ">>> " + name + " " + 60 * ">"
#        print line_number
#        print _comments
#        print text
#        print 79 * "<"
      
        markdown += text
        if last_level:
            level = last_level
        markdown += format(item, name, level+1, module, comments) + "\n"
    return markdown

def help():
    """
Return the following message:

    docgen [options] module

    options: -h, --help .................................. display help and exit
             -i FILE, --input=FILE ....................... Python module source file
             -o OUTPUT, --output=OUTPUT .................. documentation output
"""
    return "\n".join([line[4:] for line in inspect.getdoc(help).split("\n")[2:]])

def main(args=None):
    if args is None:
        args = sys.argv[1:]
    options, args = script.parse("help input= output=", args)
    if options.help:
        print help()
        sys.exit(0)
    elif not args or len(args) > 1:
        print help()
        sys.exit(1)
    else:
        module_name = args[0]

    module = importlib.import_module(module_name)
    filename = script.first(options.input) or inspect.getsourcefile(module)
    if filename is None:
        raise RuntimeError("missing input filename")
    source = open(filename).read()

    markdown = docgen(module, source)
    if not options.output:
        print markdown
    else:
        output = script.first(options.output)
        basename = os.path.basename(output)
        if len(basename.split(".")) >= 2:
            ext = basename.split(".")[-1]
        else:
            ext = None
        if ext == "tex":
            sh.pandoc(read="markdown", toc=True, standalone=True, write="latex", o=output, _in=markdown)
        elif ext == "pdf":
            try:
                latex = ".".join(basename.split(".")[:-1]) + ".tex"
                build = tempfile.mkdtemp()
                cwd = os.getcwd()
                os.chdir(build)
                sh.pandoc(read="markdown", toc=True, standalone=True, write="latex", o=latex, _in=markdown)
                sh.pdflatex(latex)
                sh.pdflatex(latex)
                os.chdir(cwd)
                sh.cp(os.path.join(build, latex[:-4] + ".pdf"), output)
            finally:
                try:
                    shutil.rmtree(build) # delete directory
                except OSError, e:
                    if e.errno != 2: # code 2 - no such file or directory
                        raise
        else:
            file = open(output, "w")
            file.write(markdown)
            file.close()

def test():
    # erf, does not work ???
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    main()




