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

import gdb

# We defer most type lookups to when they're needed, since they'll fail if the
# DWARF data for the relevant DSO hasn't been loaded yet, which is typically
# the case for an executable dynamically linked against glibc

type_void_ptr = gdb.lookup_type('void').pointer()
type_char_ptr = gdb.lookup_type('char').pointer()
type_unsigned_char_ptr = gdb.lookup_type('unsigned char').pointer()

sizeof_ptr = type_void_ptr.sizeof

__type_cache = {}

def caching_lookup_type(typename):
    '''Adds caching to gdb.lookup_type(), whilst still raising RuntimeError if
    the type isn't found.'''
    if typename in __type_cache:
        gdbtype = __type_cache[typename]
        if gdbtype:
            return gdbtype
        raise RuntimeError('(cached) Could not find type "%s"' % typename)
    try:
        gdbtype = gdb.lookup_type(typename)
    except RuntimeError, e:
        # did not find the type: add a None to the cache
        gdbtype = None
    __type_cache[typename] = gdbtype
    if gdbtype:
        return gdbtype
    raise RuntimeError('Could not find type "%s"' % typename)

def array_length(_gdbval):
    '''Given a gdb.Value that's an array, determine the number of elements in
    the array'''
    arr_size = _gdbval.type.sizeof
    elem_size = _gdbval[0].type.sizeof
    return arr_size/elem_size

def offsetof(typename, fieldname):
    '''Get the offset (in bytes) from the start of the given type to the given
    field'''

    # This is a transliteration to gdb's python API of:
    #    (int)(void*)&((#typename*)NULL)->#fieldname)

    t = caching_lookup_type(typename).pointer()
    v = gdb.Value(0)
    v = v.cast(t)
    field = v[fieldname].cast(_type_void_ptr)
    return long(field.address)

class MissingDebuginfo(RuntimeError):
    def __init__(self, module):
        self.module = module

def check_missing_debuginfo(err, module):
    assert(isinstance(err, RuntimeError))
    if err.args[0] == 'Attempt to extract a component of a value that is not a (null).':
        # Then we likely are trying to extract a field from a struct but don't
        # have the DWARF description of the fields of the struct loaded:
        raise MissingDebuginfo(module)

class WrappedValue(object):
    """
    Base class, wrapping an underlying gdb.Value adding various useful methods,
    and allowing subclassing
    """
    def __init__(self, gdbval):
        self._gdbval = gdbval

    # __getattr__ just made it too confusing
    #def __getattr__(self, attr):
    #    return WrappedValue(self.val[attr])

    def field(self, attr):
        return self._gdbval[attr]

    def __str__(self):
        return str(self._gdbval)

#    def address(self):
#        return long(self._gdbval.cast(type_void_ptr))

    def is_null(self):
        return long(self._gdbval) == 0

class WrappedPointer(WrappedValue):
    def as_address(self):
        return long(self._gdbval.cast(type_void_ptr))

    def __str__(self):
        return ('<%s for inferior 0x%x>'
                % (self.__class__.__name__,
                   self.as_address()
                   )
                )

if sizeof_ptr == 4:
    def fmt_addr(addr):
        return '0x%08x' % addr
else:
    # Assume 64-bit:
    def fmt_addr(addr):
        return '0x%016x' % addr

def fmt_size(size):
    '''
    Pretty-formatting of numeric values: return a string, subdividing the
    digits into groups of three, using commas
    '''
    s = str(size)
    result = ''
    while len(s)>3:
        result = ',' + s[-3:] + result
        s = s[0:-3]
    result = s + result
    return result

def as_hexdump_char(b):
    '''Given a byte, return a string for use by hexdump, converting
    non-printable/non-ASCII values as a period'''
    if b>=0x20 and b < 0x80:
        return chr(b)
    else:
        return '.'

def sign(amt):
    if amt >= 0:
        return '+'
    else:
        return '' # the '-' sign will come from the numeric repr

class Usage(object):
    '''Information about an in-use area of memory'''
    def __init__(self, start, size, category=None, hd=None):
        assert isinstance(start, long)
        assert isinstance(size, long)

        self.start = start
        self.size = size
        self.category = category
        self.hd = hd

    def __repr__(self):
        result = 'Usage(%s, %s' % (hex(self.start), hex(self.size))
        if self.category:
            result += ', %r' % self.category
        if self.hd:
            result += ', hd=%r' % self.hd
        return result + ')'

    def __hash__(self):
        return hash(self.start) & hash(self.size) & hash(self.category)

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def ensure_category(self):
        if self.category is None:
            self.category = categorize(self.start, self.size)

    def ensure_hexdump(self):
        if self.hd is None:
            self.hd = hexdump_as_bytes(self.start, 32)


def hexdump_as_bytes(addr, size):
    addr = gdb.Value(addr).cast(type_unsigned_char_ptr)
    bytebuf = []
    for j in range(size):
        ptr = addr + j
        b = int(ptr.dereference())
        bytebuf.append(b)
    return (' '.join(['%02x' % b for b in bytebuf])
            + ' |' 
            + ''.join([as_hexdump_char(b) for b in bytebuf])
            + '|')

def hexdump_as_long(addr, count):
    addr = gdb.Value(addr).cast(caching_lookup_type('unsigned long').pointer())
    bytebuf = []
    longbuf = []
    for j in range(count):
        ptr = addr + j
        long = ptr.dereference()
        longbuf.append(long)
        bptr = gdb.Value(ptr).cast(type_unsigned_char_ptr)
        for i in range(sizeof_ptr):
            bytebuf.append(int((bptr + i).dereference()))
    return (' '.join([fmt_addr(long) for long in longbuf])
            + ' |' 
            + ''.join([as_hexdump_char(b) for b in bytebuf])
            + '|')


class Table(object):
    '''A table of text/numbers that knows how to print itself'''
    def __init__(self, columnheadings=None, rows=[]):
        self.numcolumns = len(columnheadings)
        self.columnheadings = columnheadings
        self.rows = []
        self._colsep = '  '

    def add_row(self, row):
        assert len(row) == self.numcolumns
        self.rows.append(row)
        
    def write(self, out):
        colwidths = self._calc_col_widths()

        self._write_row(out, colwidths, self.columnheadings)

        self._write_separator(out, colwidths)

        for row in self.rows:
            self._write_row(out, colwidths, row)

    def _calc_col_widths(self):
        result = []
        for colIndex in xrange(self.numcolumns):
            result.append(self._calc_col_width(colIndex))
        return result

    def _calc_col_width(self, idx):
        cells = [str(row[idx]) for row in self.rows]
        heading = self.columnheadings[idx]
        return max([len(c) for c in (cells + [heading])])

    def _write_row(self, out, colwidths, values):
        for i, (value, width) in enumerate(zip(values, colwidths)):
            if i > 0:
                out.write(self._colsep)
            formatString = "%%%ds" % width # to generate e.g. "%20s"
            out.write(formatString % value)
        out.write('\n')

    def _write_separator(self, out, colwidths):
        for i, width in enumerate(colwidths):
            if i > 0:
                out.write(self._colsep)
            out.write('-' * width)
        out.write('\n')

class UsageSet(object):
    def __init__(self, usage_list):
        self.usage_list = usage_list

        # Ensure we can do fast lookups:
        self.usage_by_address = dict([(long(u.start), u) for u in usage_list])

    def set_addr_category(self, addr, category, visited=None, debug=False):
        '''Attempt to mark the given address as being of the given category,
        whilst maintaining a set of address already visited, to try to stop
        infinite graph traveral'''
        if visited:
            if addr in visited:
                if debug:
                    print 'addr 0x%x already visited (for category %r)' % (addr, category)
                return False
            visited.add(addr)

        if addr in self.usage_by_address:
            if debug:
                print 'addr 0x%x found (for category %r)' % (addr, category)
            self.usage_by_address[addr].category = category
            return True
        else:
            if debug:
                print 'addr 0x%x not found (for category %r)' % (addr, category)

class PythonCategorizer(object):
    '''
    Logic for categorizing buffers owned by Python objects.
    (Done as an object to capture the type-lookup state)
    '''
    def __init__(self):
        '''This will raise a TypeError if the types aren't available (e.g. not
        a python app, or debuginfo not available'''
        self._type_PyDictObject_ptr = caching_lookup_type('PyDictObject').pointer()
        self._type_PyListObject_ptr = caching_lookup_type('PyListObject').pointer()
        self._type_PySetObject_ptr = caching_lookup_type('PySetObject').pointer()
        self._type_PyUnicodeObject_ptr = caching_lookup_type('PyUnicodeObject').pointer()
        self._type_PyGC_Head = caching_lookup_type('PyGC_Head')

    @classmethod
    def make(cls):
        '''Try to make a PythonCategorizer, if debuginfo is available; otherwise return None'''
        try:
            return cls()
        except RuntimeError:
            return None

    def categorize(self, u, usage_set):
        '''Try to categorize a Usage instance within an UsageSet (which could
        lead to further categorization)'''
        if u.category == 'python dict':
            dict_ptr = gdb.Value(u.start + self._type_PyGC_Head.sizeof).cast(self._type_PyDictObject_ptr)
            ma_table = long(dict_ptr['ma_table'])
            usage_set.set_addr_category(ma_table, 'PyDictEntry table')
            return True

        elif u.category == 'python list':
            list_ptr = gdb.Value(u.start + self._type_PyGC_Head.sizeof).cast(self._type_PyListObject_ptr)
            ob_item = long(list_ptr['ob_item'])
            usage_set.set_addr_category(ob_item, 'PyListObject ob_item table')
            return True

        elif u.category == 'python set':
            set_ptr = gdb.Value(u.start + self._type_PyGC_Head.sizeof).cast(self._type_PySetObject_ptr)
            table = long(set_ptr['table'])
            usage_set.set_addr_category(table, 'PySetObject setentry table')
            return True

        elif u.category == 'python unicode':
            unicode_ptr = gdb.Value(u.start).cast(self._type_PyUnicodeObject_ptr)
            m_str = long(unicode_ptr['str'])
            usage_set.set_addr_category(m_str, 'PyUnicodeObject buffer')
            return True

        elif u.category == 'python sqlite3.Statement':
            ptr_type = caching_lookup_type('pysqlite_Statement').pointer()
            obj_ptr = gdb.Value(u.start).cast(ptr_type)
            #print obj_ptr.dereference()
            from heap.sqlite import categorize_sqlite3
            for fieldname, category, fn in (('db', 'sqlite3', 
                                             categorize_sqlite3), ('st', 'sqlite3_stmt', None)):
                field_ptr = long(obj_ptr[fieldname])
                
                # sqlite's src/mem1.c adds a a sqlite3_int64 (size) to the front
                # of the allocation, so we need to look 8 bytes earlier to find
                # the malloc-ed region:
                malloc_ptr = field_ptr - 8

                # print u, fieldname, category, field_ptr
                if usage_set.set_addr_category(malloc_ptr, category):
                    if fn:
                        fn(field_ptr, usage_set, set())
            return True

        elif u.category == 'python rpm.hdr':
            ptr_type = caching_lookup_type('struct hdrObject_s').pointer()
            if ptr_type:
                obj_ptr = gdb.Value(u.start).cast(ptr_type)
                # print obj_ptr.dereference()
                h = obj_ptr['h']
                if usage_set.set_addr_category(long(h), 'rpm Header'):
                    blob = h['blob']
                    usage_set.set_addr_category(long(blob), 'rpm Header blob')

        elif u.category == 'python rpm.mi':
            ptr_type = caching_lookup_type('struct rpmmiObject_s').pointer()
            if ptr_type:
                obj_ptr = gdb.Value(u.start).cast(ptr_type)
                print obj_ptr.dereference()
                mi = obj_ptr['mi']
                if usage_set.set_addr_category(long(h), 'rpmdbMatchIterator'):
                    pass
                    #blob = h['blob']
                    #usage_set.set_addr_category(long(blob), 'rpm Header blob')

        # Not categorized:
        return False


def categorize_usage_list(usage_list):
    '''Do a "full-graph" categorization of the given list of Usage instances
    For example, if p is a (PyDictObject*), then mark p->ma_table and p->ma_mask
    accordingly
    '''
    usage_set = UsageSet(usage_list)
    visited = set()

    # Precompute some types, if available:
    pycategorizer = PythonCategorizer.make()

    for u in usage_list:
        # Cover the simple cases, where the category can be figured out directly:
        u.ensure_category()

        # Try to categorize buffers used by python objects:
        if pycategorizer:
            if pycategorizer.categorize(u, usage_set):
                continue



def categorize(addr, size):
    '''Given an in-use block, try to guess what it's being used for'''
    from heap.python import as_python_object
    pyop = as_python_object(addr)
    if pyop:
        try:
            ob_type = WrappedPointer(pyop.field('ob_type'))
            tp_name = ob_type.field('tp_name').string()
            return 'python %s' % str(tp_name)
        except (RuntimeError, UnicodeEncodeError, UnicodeDecodeError):
            # If something went wrong, assume that this wasn't really a python
            # object, and fall through:
            pass

    # C++ detection: only enabled if we can capture "execute"; there seems to
    # be a bad interaction between pagination and redirection: all output from
    # "heap" disappears in the fallback form of execute, unless we "set pagination off"
    from heap.compat import has_gdb_execute_to_string
    #  Disable for now, see https://bugzilla.redhat.com/show_bug.cgi?id=620930
    if False: # has_gdb_execute_to_string:
        from heap.cplusplus import get_class_name
        cpp_cls = get_class_name(addr, size)
        if cpp_cls:
            return cpp_cls

    s = as_nul_terminated_string(addr, size)
    if s and len(s) > 2:
        return 'string data'

    # Uncategorized:
    return 'uncategorized data'

def as_nul_terminated_string(addr, size):
    # Does this look like a NUL-terminated string?
    ptr = gdb.Value(addr).cast(type_char_ptr)
    try:
        s = ptr.string(encoding='ascii')
        return s
    except (RuntimeError, UnicodeDecodeError):
        # Probably not string data:
        return None

def iter_usage():
    # Iterate through glibc, and within that, within Python arena blocks, as appropriate
    from heap.glibc import get_ms
    from heap.python import ArenaDetection, PyArenaPtr, ArenaObject
    ms = get_ms()

    pyarenas = ArenaDetection()

    for i, chunk in enumerate(ms.iter_mmap_chunks()):
        mem_ptr = chunk.as_mem()
        chunksize = chunk.chunksize()

        # Locate python arenas in suitably-large areas (non-mmapped chunks
        # won't be big enough, I believe):
        arena = pyarenas.as_py_arena(mem_ptr, chunksize)
        if arena:
            for u in arena.iter_usage():
                yield u
        else:
            yield Usage(long(mem_ptr), chunksize)

    for chunk in ms.iter_sbrk_chunks():
        mem_ptr = chunk.as_mem()
        chunksize = chunk.chunksize()
        if chunk.is_inuse():
            yield Usage(long(mem_ptr), chunksize)

            
    


