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

# C++ support
import re

import gdb

from heap import caching_lookup_type, looks_like_ptr
from heap.compat import execute

void_ptr_ptr = caching_lookup_type('void').pointer().pointer()

def get_class_name(addr, size):
    # Try to detect a vtable ptr at the top of this object:
    vtable = gdb.Value(addr).cast(void_ptr_ptr).dereference()
    if not looks_like_ptr(vtable):
        return None

    info = execute('info sym (void *)0x%x' % int(vtable))
    # "vtable for Foo + 8 in section .rodata of /home/david/heap/test_cplusplus"
    m = re.match('vtable for (.*) \+ (.*)', info)
    if m:
        return m.group(1)
    # Not matched:
    return None


def as_cplusplus_object(addr, size):
    print(get_class_name(addr))
    pass
