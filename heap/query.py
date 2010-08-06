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

class Expression(object):
    def eval_(self, u):
        raise NotImplementedError

    def __eq__(self, other):
        return (self.__class__ == other.__class__
                and self.__dict__ == other.__dict__)

class Constant(Expression):
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return 'Constant(%r)' % (self.value,)

    def eval_(self, u):
        return self.value

class GetAttr(Expression):
    def __init__(self, attrname):
        self.attrname = attrname

    def __repr__(self):
        return 'GetAttr(%r)' % (self.attrname,)

    def eval_(self, u):
        if self.attrname == 'category':
            if u.category == None:
                u.ensure_category()
        return getattr(u, self.attrname)

class BinaryOp(Expression):
    def __init__(self, lhs, rhs):
        self.lhs = lhs
        self.rhs = rhs

class Comparison(BinaryOp):
    def __init__(self, lhs, rhs):
        BinaryOp.__init__(self, lhs, rhs)

    def __repr__(self):
        return '%s(%r, %r)' % (self.__class__.__name__, self.lhs, self.rhs)

    def eval_(self, u):
        lhs_val = self.lhs.eval_(u)
        rhs_val = self.rhs.eval_(u)
        return self.cmp_(lhs_val, rhs_val)

    def cmp_(self, lhs, rhs):
        raise NotImplementedError

class Comparison__le__(Comparison):
    def cmp_(self, lhs, rhs):
        return lhs <= rhs

class Comparison__lt__(Comparison):
    def cmp_(self, lhs, rhs):
        return lhs <  rhs

class Comparison__eq__(Comparison):
    def cmp_(self, lhs, rhs):
        return lhs == rhs

class Comparison__ne__(Comparison):
    def cmp_(self, lhs, rhs):
        return lhs != rhs

class Comparison__ge__(Comparison):
    def cmp_(self, lhs, rhs):
        return lhs >= rhs

class Comparison__gt__(Comparison):
    def cmp_(self, lhs, rhs):
        return lhs >  rhs


class And(BinaryOp):
    def __repr__(self):
        return 'And(%r, %r)' % (self.lhs, self.rhs)

    def eval_(self, u):
        # Short-circuit evaluation:
        if not self.lhs.eval_(u):
            return False
        return self.rhs.eval_(u)

class Or(BinaryOp):
    def __repr__(self):
        return 'Or(%r, %r)' % (self.lhs, self.rhs)

    def eval_(self, u):
        # Short-circuit evaluation:
        if self.lhs.eval_(u):
            return True
        return self.rhs.eval_(u)

class Not(Expression):
    def __init__(self, inner):
        self.inner = inner
    def __repr__(self):
        return 'Not(%r)' % (self.inner, )
    def eval_(self, u):
        return not self.inner.eval_(u)



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
            if self.filter_.eval_(u):
                yield u


def do_query(args):
    from heap import fmt_addr, Table
    from heap.parser import parse_query

    if args == '':
        # if no query supplied, select everything:
        filter_ = Constant(True)
    else:
        filter_ = parse_query(args)

    if False:
        print args
        print filter_

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
    print
    
    
