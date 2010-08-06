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

import sys

import gdb

class UsageFilter(object):
    def matches(self, u):
        raise NotImplementedError

class CompoundUsageFilter(object):
    def __init__(self, *nested):
        self.nested = nested

class And(CompoundUsageFilter):
    def matches(self, u):
        for n in self.nested:
            if not n.matches(u):
                return False
        return True

class AttrFilter(UsageFilter):
    def __init__(self, attrname, value):
        self.attrname = attrname
        self.value = value

    def matches(self, u):
        if self.attrname == 'category':
            if u.category == None:
                u.ensure_category()
        actual_value = getattr(u, self.attrname)
        return self._do_match(actual_value)

    def _do_match(self, actual):
        raise NotImplementedError

class AttrGt(AttrFilter):
    def _do_match(self, actual):
        return actual >= self.value

class Column(object):
    def __init__(self, name, getter, formatter):
        self.name = name
        self.getter = getter
        self.formatter = formatter


class Query(object):
    def __init__(self, filter_):
        self.filter_ = filter_

    def __iter__(self):
        from heap import iter_usage
        for u in iter_usage():
            if self.filter_.matches(u):
                yield u


def do_query(args):
    from heap import fmt_addr, Table

    print repr(args)

    # FIXME: implement a real parser
    filter_ = AttrGt('size', 10000)

    columns = [Column('Start',
                      lambda u: u.start,
                      fmt_addr),
               Column('End',
                      lambda u: u.start + u.size - 1,
                      fmt_addr
                      ),
               Column('Domain',
                      lambda u: u.category.domain,
                      None),
               Column('Kind',
                      lambda u: u.category.kind,
                      None),
               Column('Detail',
                      lambda u: u.category.detail,
                      None),
               Column('Hexdump',
                      lambda u: u.hexdump,
                      None),
               ]
               
    t = Table([col.name for col in columns])

    for u in Query(filter_):
        u.ensure_hexdump()
        u.ensure_category()

        if u.category:
            domain = u.category.domain
            kind = u.category.kind
            detail = u.category.detail
            if not detail:
                detail = ''        
        else:
            domain = ''
            kind = ''
            detail = ''

        t.add_row([fmt_addr(u.start),
                   fmt_addr(u.start + u.size - 1),
                   domain,
                   kind,
                   detail,
                   u.hd])

    t.write(sys.stdout)
    
    
