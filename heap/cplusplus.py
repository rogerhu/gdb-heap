# C++ support
import re

import gdb

from heap.compat import execute

def get_class_name(addr, size):
    # Try to detect a vtable ptr at the top of this object:
    info = execute('info sym *(void **)0x%x' % addr)
    # "vtable for Foo + 8 in section .rodata of /home/david/heap/test_cplusplus"
    m = re.match('vtable for (.*) \+ (.*)', info)
    if m:
        return m.group(1)
    # Not matched:
    return None
    

def as_cplusplus_object(addr, size):
    print get_class_name(addr)
    pass
