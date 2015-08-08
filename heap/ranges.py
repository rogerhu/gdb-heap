# -*- coding: utf-8 -*-
# Copyright (C) 2015  Stefan Bühler
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

from heap import caching_lookup_type, fmt_addr

class Range(object):
    '''Memory range'''

    def __init__(self, start, end):
        if start > end:
            raise ValueError("Invalid range")
        self.start = start
        self.end = end

    def __str__(self):
        return ('%s - %s') % (fmt_addr(self.start), fmt_addr(self.end))

    @property
    def last(self):
        return self.end - 1

    @property
    def empty(self):
        return self.start == self.end

    def __cmp__(self, other):
        return cmp((self.start, self.end), (other.start, other.end))

def ranges():
    import re
    PARSE_RANGE_LINE = re.compile('^\t(0x[0-9a-fA-F]+) - (0x[0-9a-fA-F]+)')

    from heap.compat import execute

    result = []
    for line in execute('info file').splitlines():
        match = PARSE_RANGE_LINE.match(line)
        if not match: continue
        (start, end) = match.groups()
        result.append(Range(int(start, 16), int(end, 16)))
    return result

def merged_ranges():
    '''merge neighbours, drop empty ranges'''
    cur_range = None
    result = []
    for r in sorted(ranges()):
        if r.empty: continue
        if cur_range:
            if cur_range.end >= r.start:
                # merge range
                cur_range = Range(cur_range.start, max(cur_range.end, r.end))
            else:
                # no overlap, move forward
                result.append(cur_range)
                cur_range = r
        else:
            cur_range = r
    if cur_range:
        result.append(cur_range)

    return result
