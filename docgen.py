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
__version__ = "0.0.0a1"

#
# TODOs
# ------------------------------------------------------------------------------
#
#   - use syntaxtic (source) analysis to produce the function signatures ... ok.
#  
#   - manage to documention Cython extension classes ? ..................... ok.
#
#   - handle `wrapper_descriptor` type as a function (Cython). Get the type
#     as type(str.__dict__['__add__']). Do the same with method_descriptor
#     obtained as type(str.center)
#
#   - handle assignment of class and function differently from their definition.
#     (examine the type info and not only the type of the object). Use cases:
#     `__str__ = __repr__` in a class, multiple names of classes/functions to
#     preserve a legacy API, etc.
#
#   - manage the documentation / docstrings of properties.
#
#   - decorators.
#
#   - flag to hide "private" fields. Or at least, their doc should be deactivated
#     by default.
#  
#   - generalize the trick used to compose the document title ? Combine the
#     object tt name with the one-liner description ? So that the titles are
#     not 100% tt (code) anymore but (bold) text, made for the human ? Or even,
#     hide the code, signature, etc one level below ? Would be ok for classes,
#     where the short doc is a title, not such much for functions for which the
#     one-liner is a sentence (action performed by the function).
#
#   - Test specifically for pandoc 1.9 (or <= ?) ? Pinpoint the last version
#     with the "classic" JSON model that is compatible with my implementation.
#     Study the (apparently unstable and whose doc does not macth the reality
#     of the JSON document model)

#
# Pandoc Document Model
# ------------------------------------------------------------------------------
#

# Rk: need to stick with pandoc 1.9 for now, the later versions have been
#     messing seriously with the JSON representation (and it's still not
#     stable or works as advertised AFAICT).

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
        Convert the `PandocType instance` into a native Python structure that 
        may be encoded into text by `json.dumps`.
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

class Table(Block):
    pass

class DefinitionList(Block):
    pass

class BulletList(Block):
    pass

class OrderedList(Block):
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
# **Remark:** `Space` is encoded as a string in the json exported by pandoc.
# That's kind of a problem because we won't typematch it like the other
# instances and searching for the string "Space" may lead to false positive.
# The only way to deal with it is to be aware of the context where the Space
# atom (inline) may appear but here we typically are not aware of that.
#

class Strong(Inline):
    pass

class Math(Inline):
    pass


# TODO: check Pandoc version: in 1.12(.1 ?), change in the json output 
#       structure ... Need to handle both kind of outputs ... selection
#       of the format as a new argument to __json__ ? The Text.Pandoc.Definition
#       has been moved to pandoc-types <http://hackage.haskell.org/package/pandoc-types>.
#       Detect the format used by the conversion of a simple document ? Fuck, 
#       In need to be able to access an "old" version of pandoc (the one packaged
#       for ubuntu 12.04 ?). Ah, fuck, all this is a moving target. In 12.1,
#       that's "tag" and "contents", but changelog of 12.1 stated that it is
#       "t" and "c" ... I don't even know what version I am really using.
#       What is supposed to be stable ? There is probably 3 target: the packaged
#       ubuntu 12.04, the 1.12 installed as latest by cabal ... and the current
#       git version ... 1.12.3 ouch. What's in Ubuntu 13.04 ? 13.10 ? The 1.11.1
#       Errr ... Try to build from git the git version and see if there is
#       really a change in the JSON format ?
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
    #print "***text:", text
    json_text = str(sh.pandoc(read="markdown", write="json", _in=text))
    json_ = json.loads(json_text)
    #import pprint
    #pp = pprint.PrettyPrinter(indent=2).pprint
    #print "***json:"
    #pp(json_)
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
# **TODO:** insert HorizontalRule before every level 2 section. Unless I do that
# at the LaTeX level ? Or don't do it generally, just before functions
# and classes (no transform, do it directly during markdown generation) ?
#

#
# ------------------------------------------------------------------------------
#

#
# **TODO:**
# hierarchical structure: class method docs should be browsed too.
# return a list that contains [name, item, docstring, children] ?
# add extra stuff such as line / file, source code, etc. ? Put this
# stuff into an info dict ?
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

#def _get_comments(module):
#    comments = []
#    try:
#        source = inspect.getsource(module)
#    except IOError:
#        return comment
#    pattern = "^#\s*\n(# [^\n]*\n)*#\s*\n"
#    for match in re.finditer(pattern, source, re.MULTILINE):
#        line_number = source.count("\n", 0, match.start()) + 1
#        comment = match.group(0)
#        comment = "\n".join(line[2:] for line in comment.split("\n"))
#        comments.append((line_number, comment))
#    return comments
       
def last_header_level(markdown):
    doc = Pandoc.read(markdown)
    levels = [item.args[0] for item in doc.iter() if isinstance(item, Header)]
    if levels:
        return levels[-1]

#
# Source Code Analysis
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

# DEPRECATED:
#
# def is_blank(line):
#     """Identify blank lines"""
#     whitespace = "\s*"
#     return re.match(whitespace, line).group(0) == line


# TODO: single function call, convert one way or another based on the
#       number of arguments ? And therefore, turn the Locator into a 
#       closure ...
class Locator(object):
    """Convert locations in text.

    Locations are described either by
    `offset`, an absolute character offset with respect to the
    start of `text` 
    or
    a pair `(lineno, rel_offset)` of a line number offset
    (starts at `0`) and an offset relative to the start of the line.
    """
    def __init__(self, text):
        """
        Create a `Locator` instance for the string `text`.
        """
        self._offsets = [0]
        for line in text.split("\n"):
            self._offsets.append(self._offsets[-1] + len(line) + 1)

    def __call__(self, offset):
        """
        Compute the location `(lineno, rel_offset)`
        """
        for i, _offset in enumerate(self._offsets):
            if offset < _offset:
                return (i - 1, offset - self._offsets[i-1])

    def offset(self, lineno, rel_offset):
         """
         Compute the location `offset`
         """
         return sum([len for len in self._offsets[:lineno]] + [rel_offset], 0)

#
# -----
#

def finder(symbol, pattern=None, *flags):
    """
    Create a function that searches for locations of a a pattern in a text.

    Arguments
    ---------

      - `symbol`: the name of the symbol to search,
      - `pattern`: a regular expression, defaults to `re.escape(symbol)`,
      - `flags`: extra flags passed to `re.search` function internally.

    Returns
    -------

      - a finder function whose arguments are :

          - `text`: the text to be searched, 
          - `start`: the start index, defaults to `0`.
        
        that returns:

          - `(symbol, start, end)` or `None` when no match is found.
    """
    if pattern is None:
        pattern = "({0})".format(re.escape(symbol))
    pattern = re.compile(pattern, *flags)
    def finder_(text, start=0):
        match = pattern.search(text, start)
        if match is None:
            return None
        else:
            start, end = match.span(1)
            return symbol, start, end
    finder_.__name__ = symbol
    return finder_

# We don't need a First then Longest then "First in pattern list" sorter ?
# This is what is done implicitly ? Can we trust list.sort to return the
# first item in the list among those that are equally sorted ? Yes, this
# is a stable sort ...
def sort_items(list):
    """First-then-longest sorter

    This function sorts in-place a list of `(symbol, start, end)` items,
    in a way that the items with the lowest `start` index appear 
    first, and when such indices are equal, the item with the highest `end` 
    index appears first.
    """
    first_then_longest = lambda item: (item[1], -item[2])
    list.sort(key=first_then_longest)

def tokenize(text):
    """
    Tokenizer

    Produce a sequence of `(symbol, start, end)` items where `symbol` 
    belongs to the following list of strings:

            (  )  [  ]  {  }  BLANKLINE  COMMENT  LINECONT  STRING

    """
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
    items = []
    while start < len(text):
        results = []
        for find in finders:
            result = find(text, start)
            if result is not None:
                results.append(result)
        if results:
            sort_items(results)
            result = results[0]
            items.append(result)
            start = result[2]
        else:
            break
    return items

# Rk: now the "largest" objects (enclosing braces) are returned AFTER the
#     enclosed objects. Maybe we don't care ? But it's contrary to the
#     classic linearization of the hierarchy.
def scan(text):
    """
    Scan the source code `text` for atomic and scoping patterns.

    Produce a a sequence of `(symbol, start, end)` items where `symbol` 
    belongs to the following list of strings:

            ()  []  {}  BLANKLINE  COMMENT  LINECONT  STRING

    The items may be overlapping.
    """
    match = {"(": ")", "[": "]", "{": "}", ")": "(", "]": "[", "}": "{"}
    wait_for = []
    items = []

    for symbol, start, end in tokenize(text):
        if name in ["(", "[", "{"]:
            wait_for.append((match[symbol], start))
        elif wait_for and symbol == wait_for[-1][0]:
            _, start = wait_for.pop()
            items.append((match[symbol] + symbol, start, end))
        else:
            items.append((symbol, start, end))

    sort_items(items)
    return items

def skip_lines(text):
    """
    Lines to skip during the indentation analysis.
    """
    lines = []
    locator = Locator(text)
    for name, start, end in scan(text):
        start, end = locator(start), locator(end)
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

def tab_match(line, tabs):
    """
    Analyze the indentation of a line with respect to a sequence of indents.

    Arguments
    ---------

      - `line`: a text string,

      - `tabs`: a sequence of non-empty whitespace strings.

    Returns
    -------

      - `match`: the largest starting sequence of `tabs` found at the
        start of the line,

      - `extra`: an extra whitespace element found after the full `tabs` sequence, 
                 or otherwise `None`.

    Raises
    ------

    A `ValueError` exception is raised if the `tabs` list is matched only 
    partially but there is some extra whitespace found after it.
    """
    tab_search = re.compile("^[ \t\r\f\v]+", re.MULTILINE).search
    _tabs = tabs[:]
    matched = []

    while _tabs:
        tab = _tabs.pop(0)
        if line.startswith(tab):
            matched.append(tab)
            line = line[len(tab):]
        else:
            break

    match = tab_search(line)
    if match:
        extra = match.group(0)
    else:
        extra = None

    if matched == tabs or not extra:
        return matched, extra
    else:
        raise ValueError("indentation error")

def indents(text):
    """
    Return the indents of a source code.

    The result is a list of `(lineno, delta)` where:

      - `lineno` is a line number offset (starts with `0`),

      - `delta` is the number of extra indents (it may be negative).
    """
    skip = skip_lines(text)
    tabs = []
    indents = []
    for i, line in enumerate(text.split("\n")):
        if i not in skip:
            match, extra = tab_match(line, tabs)
            if extra:
                indents.append((i, +1))
                tabs.append(extra)
            else:
                indents.append((i, len(match) - len(tabs)))
                tabs = tabs[:len(match)]
    return indents

def parse_declaration(line):
    finders  = []
    finders += [finder("function"  , r"^\s*c?p?def\s+([_0-9a-zA-Z]+)\s*\(")]
    finders += [finder("assignment", r"^\s*([_0-9a-zA-Z]+)\s*=\s*")]
    finders += [finder("class"     , r"^\s*(?:cdef)?\s*class\s+([_0-9a-zA-Z]+)")]
    results, result = [], None
    for find in finders:
        result = find(line)
        if result is not None:
            results.append(result)
    if results:
        sort_items(results)
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
#       In info, use None (for lineno, name, type) when it is required.
#       
# Q: how should line continuations be handled ? In a first approach,
#    we don't do anything but later, maybe the lineno should be 
#    replaced with a RANGE of lineno ? 



class Info(object):
    """
    Lighweight Records
    """
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

# Rk: splitlines does not honor trailing newlines, use split("\n") instead.

# TODO: check that all blanklines are here.
def make_tree(text):
    """
    Create a nested structure based on the indentation of source code.

    Argument
    --------

      - `text`: a source code string

    Returns
    -------

      - `tree = (info, children)` where: 
          - `info` has `lineno`, `name`, `type` and `source` attributes, 
          - `children` is a list of `tree` items.

    """
    lines = text.split("\n")
    items = [(Info(lineno=0, name=None, type=None), [])]
    item = items[0] # current item
    prev_lineno = 0
    def push(item):
        items.append(item)
    def fold():
        item = items.pop()
        items[-1][-1].append(item)
    for lineno, tab in indents(text):
        text = "\n".join(lines[prev_lineno:lineno])
        item[0].source = text
        type, name = parse_declaration(lines[lineno])
        if tab <= 0 and len(items) >= 2:
            for _ in range(-tab + 1):
                fold()
        info = Info(lineno=lineno, name=name, type=type)
        item = (info, [])
        push(item)
        prev_lineno = lineno
    else:
        lineno = len(lines)
        source = "\n".join(lines[prev_lineno:lineno]) # no trailing newline.
        item[0].source = source
    while len(items) >= 2:
        fold()
    return items[0]


# TODO: Sometimes there are extra BLANKLINEs, get rid of them. It maybe an
#       issue with comments ???
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

#
# Documentation Formatting
# ------------------------------------------------------------------------------
#


# TODO: manage the body of docgen as yet another formatter function.

def docgen(module, source, debug=False):
    module_name = module.__name__
    tree = make_tree(source)
    tree[0].name = module_name

    objectify(tree)
    commentify(tree)
    decoratify(tree)

    if debug:
        display_tree(tree)
        print 5*"\n"


    markdown = ""

    docstring = inspect.getdoc(module) or ""
    doclines = docstring.split("\n")
    if len(doclines) == 1:
        short, long = doclines[0].strip(), ""
    elif len(doclines) >= 2 and not doclines[1].strip():
        short, long = doclines[0].strip(), "\n".join(doclines[2:])
    else:
        short, long = "\n".join(doclines)


    # TODO: refactor into `format_module`.
    markdown  = "#" + " " + tt(module_name)
    markdown += (" -- " + short + "\n\n") if short else "\n\n"
    markdown += long + "\n\n" if long else ""

    level = 2

    state = {"level": level, 
             "namespace": module_name, 
             "restore": True}

    for child in tree[1]:
        markdown += format(child, state)

    return markdown


def load_object(qualified_name):
    """
    Load an object by qualified (dotted) name.
    """
    parts = qualified_name.split(".")
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
       raise ValueError()
    for part in parts:
       try:
           object = getattr(object, part)
       except AttributeError:
           raise ValueError()
    return object

def objectify(tree, ns=None):
    """
    Annotate a tree with objects instances.

    Add `object` fields to the tree `info` structures when it makes sense.
    """
    name = tree[0].name
    if name:
        qname = (ns + "." if ns else "") + name
        try:
            tree[0].object = load_object(qname)
        except ValueError:
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
        lines = comment.split("\n")
        lines = [line[2:] for line in lines[1:-1]]
        return Markdown("\n".join(lines) + "\n")

def commentify(tree):
    source = getattr(tree[0], "source", None)
    object = getattr(tree[0], "object", None)
    if source is not None and (object is None or not isinstance(object, Markdown)):
        # Oh, c'mon, use the tokenizer ffs !
        pattern = r"^#\s*\n(?:#(?: [^\n]*|[ \t\r\f\v]*)\n)*#\s*(\n|$)"
        matches = list(re.finditer(pattern, source, re.MULTILINE))
        for i, match in enumerate(matches):
            start = match.start()
            end = match.end()
            if i == 0:
                tree[0].source = source[:start]
            if i+1 < len(matches):
                next = matches[i+1].start()
            else:
                next = len(source)
            comment = Markdown.from_comment(source[start:end])
            line_start = source.count("\n", 0, start)
            info = Info(name=None, lineno=tree[0].lineno + line_start, 
                        object=comment, type=None)
            info.source = source[start:next]
            tree[1].insert(i, (info, []))

    for child in tree[1]:
        commentify(child)

# TODO: decoratorify, then implement the corresponding formatter ? Oops,
#       slightly more complex as u have to modify a function formatter.
#       Use the state ...

class Decorator(object):
    def __init__(self, decorator):
        self.decorator = decorator
    def __str__(self):
        return self.decorator

# TODO: avoid the regexp in COMMENT or STRING content (re-scan the content,
#       based on finders instead of the raw regexp)
def decoratify(tree):
    source = getattr(tree[0], "source", None)
    object = getattr(tree[0], "object", None)
    if source is not None and (object is None or not isinstance(object, Decorator)):
        pattern = r"^\s*@.+(\n|$)"
        matches = list(re.finditer(pattern, source, re.MULTILINE))
        for i, match in enumerate(matches):
            start = match.start()
            end = match.end()
            if i == 0:
                tree[0].source = source[:start]
            if i+1 < len(matches):
                next = matches[i+1].start()
            else:
                next = len(source)
            decorator = Decorator(source[start:end].strip())
            line_start = source.count("\n", 0, start)
            info = Info(name=None, lineno=tree[0].lineno + line_start, 
                        object=decorator, type=None)
            info.source = source[start:next]
            tree[1].insert(i, (info, []))

    for child in tree[1]:
        decoratify(child)

_formatters = []

def is_public(name):
   return not name.startswith("_") or (name.startswith("__") and name.endswith("__"))

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

WrapperDescriptorType = type(str.__dict__['__add__'])
MethodDescriptorType = type(str.center)

FunctionTypes = [types.FunctionType, 
                 types.MethodType, 
                 types.BuiltinFunctionType, 
                 WrapperDescriptorType,
                 MethodDescriptorType]

@formatter(*FunctionTypes)
def format_function(tree, state):

    markdown = ""
    if is_public(tree[0].name):
        object = tree[0].object
        markdown  = state["level"] * "#" + " "

        # TODO: syntax-based signature (instead of introspection-based)
        # Quick and dirty. Need something more robust that will used multiline,
        # get rid of the ":", of potential comments, etc.

        source = tree[0].source
        # TODO: handle assignment.
        assignment = re.compile(r"\s*([_a-zA-Z])+\s*=")
        if assignment.match(source):
            markdown += tt(source.split("\n")[0].strip()) + " [`function`]\n"
        else:
            def_ = re.compile(r"\s*(?:c|cp)?def\s+(.+)$", re.MULTILINE)
            match = def_.match(source)
            if not match:
               error = "can't analyze function definition {0!r}"
               raise SyntaxError(error.format(source))

            signature = match.group(1).strip()[:-1]

            markdown += tt(signature)

            markdown += " [`function`]\n"
            markdown += "\n"

            decorators = state.get("decorator", [])
            if len(decorators) == 1:
                markdown += "decorated by: "
                markdown += tt(decorators[0]) + ".\n\n"
            elif len(decorators) >= 2:
                markdown += "decorated by:\n\n"
                for decorator in decorators:
                    markdown += "  - " + tt(decorator) + "\n"
                markdown += "\n"

            docstring = inspect.getdoc(object) or ""
            if docstring:
                doc = Pandoc.read(docstring)
                set_min_header_level(doc, state["level"] + 1)
                docstring = doc.write()
                markdown += docstring + "\n\n"

    state["decorator"] = []

    if is_public(tree[0].name):
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
    markdown = ""
    if is_public(tree[0].name):
        object = tree[0].object
        name = tree[0].name
        level = state["level"]
        markdown  = level * "#" + " "
        bases_names = [type.__name__ for type in object.__bases__] 
        markdown += tt((name + "({0})").format(", ".join(bases_names))) 
        markdown += " [`type`]\n"
        markdown += "\n"
        docstring = inspect.getdoc(object) or ""
        if docstring:
            doc = Pandoc.read(docstring)
            set_min_header_level(doc, level + 1)
            docstring = doc.write()
            markdown += docstring + "\n"
        state["level"] = level + 1
        for child in tree[1]:
            markdown += format(child, state)
        if state["restore"]:
            state["level"] = level
    return markdown



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

@formatter(Decorator)
def format_decorator(tree, state):
    # TODO: put some info in the state for the next function.
    if not state.get("decorator", None):
        state["decorator"] = []
    state["decorator"].append(tree[0].object.decorator)
    return ""

@formatter(object)
def format_object(tree, state):
    markdown = ""
    if is_public(tree[0].name):
        object = tree[0].object
        name = tree[0].name
        markdown  = state["level"] * "#" + " " + tt(name) 
        markdown += " [`{0}`] \n".format(type(object).__name__)
        markdown += "\n"
        if isinstance(object, unicode):
            string = object.encode("utf-8")
        else:
            string = str(object)
        if len(string) >= 800:
            string = string[:400] + " ... " + string[-400:]

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




#def get_decl(line):
#    """
#    Return `(name, type)`
#    """
#    function = r"(?:c?p?def)\s+(?P<name>[_0-9a-zA-Z]+)\("
#    type = r"(class)\s+(?P<name>[_0-9a-zA-Z]+)("
#    assign = r"(?P<name>[_0-9a-zA-Z]+)\s*\+?="

#
# ------------------------------------------------------------------------------
#

## BUG: any item with `inf` as a line_number (meaning unknown line number,
##      flush to the end will flush out ALL of the source comments, including
##      those out of the class declaration for example. 
##      If we could reduce the unknown decl line numbers to 0 that would be 
##      extra nice ... Do our best and otherwise EXCLUDE the objects whose
##      line number is unknown ?
##      Base the improvement on source analysis (with re), something that could
##      be working on cython too ?
#def format_comments(comments, up_to=INF):
#    markdown = ""
#    level = None
#    while True:
#        try:
#            line_number, comment = comments.pop(0)
#            if line_number > up_to:
#                comments.insert(0, (line_number, comment))
#                break
#            else:
#                markdown += comment
#        except IndexError:
#            break
#    if markdown:
#        return markdown, last_header_level(markdown)
#    else:
#        return "", None
#     

#def _format(item, name=None, level=1, module=None, comments=None):
#    if module is None and isinstance(item, types.ModuleType):
#        module = item
#    if comments is None:
#        comments = get_comments(module)
#    name, item, children = object_tree(item, name)
#    last_name = name.split(".")[-1]

#    markdown = ""
#    children = sorted(children, key=line_number_finder(item))


#    docstring = inspect.getdoc(item) or ""
#    if isinstance(item, types.ModuleType):
#        lines = docstring.split("\n")
#        if lines:
#            short = lines[0] # TODO: what if there is no short desc. ?
#            long  = "\n".join(lines[1:]).strip()
#        else:
#            short = ""
#            long  = ""

#        # TODO: make the distinction in short between titles (to be merged
#        # in the title, that does not end with a "." and a short description,
#        # that should not be merged (and ends with a ".").
#        markdown = level * "#" + " " + tt(name) + " -- " + short + "\n\n"
#        markdown += long + "\n\n"
#    elif isinstance(item, (types.FunctionType, types.MethodType)):
#        markdown += level * "#" + " " + tt(signature(item))+ " [`function`]".format(signature(item))
#        markdown += "\n\n"
#        doc = Pandoc.read(docstring)
#        set_min_header_level(doc, level + 1)
#        docstring = doc.write()
#        markdown += docstring + "\n"
#    elif isinstance(item, type):
#        markdown += level * "#" + " " + tt((last_name + "({0})").format(", ".join(t.__name__ for t in item.__bases__))) + " [`type`]"
#        markdown += "\n\n"
#        markdown += docstring + "\n\n"
#    else: # "primitive" types
#        # distinguish "constants" (with syntax __stuff__ or STUFF) from
#        # variables ? Dunno ...
#        markdown += level * "#" + " " + tt(last_name) + " [`{0}`]".format(type(item).__name__) + "\n\n"
#        if isinstance(item, unicode):
#            string = item.encode("utf-8")
#        else:
#            string = str(item)
#        markdown += tt(string) + "\n\n"
#        

#    for name, item, _children in children:
#        line_number = line_number_finder(module)((name, item, _children))
#        _comments = copy.copy(comments)
#        text, last_level = format_comments(comments, up_to=line_number)
##        print ">>> " + name + " " + 60 * ">"
##        print line_number
##        print _comments
##        print text
##        print 79 * "<"
#      
#        markdown += text
#        if last_level:
#            level = last_level
#        markdown += format(item, name, level+1, module, comments) + "\n"
#    return markdown

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
    options, args = script.parse("help input= output= debug", args)
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

    debug = bool(options.debug)

    markdown = docgen(module, source, debug)
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
            try: # keep that somewhere, but use pandoc to generate the pdf ?
                latex = ".".join(basename.split(".")[:-1]) + ".tex"
                build = tempfile.mkdtemp()
                cwd = os.getcwd()
                os.chdir(build)
                sh.pandoc(read="markdown", toc=True, standalone=True, write="latex", o=latex, _in=markdown)
                sh.xelatex(latex)
                sh.xelatex(latex)
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




