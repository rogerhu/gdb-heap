# Copyright (C) 2010  David Hugh Malcolm
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


# This is a support script for selftest.py

# It creates various kinds of object, so that we can verify that gdb-heap
# detects them (and their supporting buffers)


# Four different kinds of (x, y) coordinate:

try:
    from collections import namedtuple
    NamedTuple = namedtuple('NamedTuple', ('x', 'y'))
except ImportError:
    NamedTuple = None

class OldStyle:
    def __init__(self, x, y):
        self.x = x
        self.y = y

class NewStyle(object):
    def __init__(self, x, y):
        self.x = x
        self.y = y

class NewStyleWithSlots(object):
    __slots__ = ('x', 'y')
    def __init__(self, x, y):
        self.x = x
        self.y = y

objs = []
types = [OldStyle, NewStyle, NewStyleWithSlots]
if NamedTuple:
    types.append(NamedTuple)
for impl in types:
    objs.append(impl(x=3, y=4))
print(objs)


# Test creating an object with more than 8 attributes, so that the __dict__
# has an external PyDictEntry buffer.
# We will test to see if this detectable in the selftest.
class OldStyleManyAttribs:
    def __init__(self, **kwargs):
        self.__dict__ = kwargs

class NewStyleManyAttribs(object):
    def __init__(self, **kwargs):
        self.__dict__ = kwargs


# Create instance with 9 attributes:
old_style_many = OldStyleManyAttribs(**dict(zip('abcdefghi', range(9))))
new_style_many = NewStyleManyAttribs(**dict(zip('abcdefghi', range(9))))



# Ensure that we have a set object that uses an externally allocated
# buffer, so that we can verify that these are detected.  To do this,
# we need a set with more than PySet_MINSIZE members (which is 8):
large_set = set(range(64))
large_frozenset = frozenset(range(64))

import sqlite3
db = sqlite3.connect(':memory:')
c = db.cursor()

# Create table
c.execute('''CREATE TABLE dummy(foo TEXT, bar TEXT, v REAL)''')

# Insert a row of data
c.execute("INSERT INTO dummy VALUES ('ostrich', 'elephant', 42.0)")

# Save (commit) the changes
db.commit()

# Don't close "c"; we want to see the objects in memory


# Ensure that the selftest's breakpoint on builtin_id is hit:
id(42)

