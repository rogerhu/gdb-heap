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

class AttrEquals(AttrFilter):
    def matches(self, u):
        if self.attrname == 'category':
            if u.category == None:
                u.ensure_category()
        actual_value = getattr(u, self.attrname)
        return actual_value == self.value

