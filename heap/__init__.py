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

from collections import namedtuple

try:
    import gdb


    # We defer most type lookups to when they're needed, since they'll fail if the
    # DWARF data for the relevant DSO hasn't been loaded yet, which is typically
    # the case for an executable dynamically linked against glibc

    type_void_ptr = gdb.lookup_type('void').pointer()
    type_char_ptr = gdb.lookup_type('char').pointer()
    type_unsigned_char_ptr = gdb.lookup_type('unsigned char').pointer()
    sizeof_ptr = type_void_ptr.sizeof

    if sizeof_ptr == 4:
        def fmt_addr(addr):
            return '0x%08x' % addr
    else:
        # Assume 64-bit:
        def fmt_addr(addr):
            return '0x%016x' % addr

except ImportError:
    # Support importing heap.parser from outside gdb
    pass


class WrongInferiorProcess(RuntimeError):
    def __init__(self, hint):
        self.hint = hint

NUM_HEXDUMP_BYTES = 20

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
        if 0:
            print('type cache miss: %r' % typename)
        gdbtype = gdb.lookup_type(typename).strip_typedefs()
    except RuntimeError as e:
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
    field = v[fieldname].cast(type_void_ptr)
    return int(field.address)

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

    # See http://sourceware.org/gdb/onlinedocs/gdb/Values-From-Inferior.html#Values-From-Inferior
    @property
    def address(self):
        return self._gdbval.address

    @property
    def is_optimized_out(self):
        return self._gdbval.is_optimized_out

    @property
    def type(self):
        return self._gdbval.type

    @property
    def dynamic_type(self):
        return self._gdbval.dynamic_type

    @property
    def is_lazy(self):
        return self._gdbval.is_lazy

    def dereference(self):
        return WrappedValue(self._gdbval.dereference())

#    def address(self):
#        return int(self._gdbval.cast(type_void_ptr))

    def is_null(self):
        return int(self._gdbval) == 0

class WrappedPointer(WrappedValue):
    def as_address(self):
        return int(self._gdbval.cast(type_void_ptr))

    def __str__(self):
        return ('<%s for inferior 0x%x>'
                % (self.__class__.__name__,
                   self.as_address()
                   )
                )

    def cast(self, type_):
        return WrappedPointer(self._gdbval.cast(type_))

    def categorize_refs(self, usage_set, level=0, detail=None):
        '''Hook for categorizing references known by the type this points to'''
        # do nothing by default:
        pass


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


class Category(namedtuple('Category', ('domain', 'kind', 'detail'))):
    '''
    Categorization of an in-use area of memory

      domain: high-level grouping e.g. "python", "C++", etc

      kind: type information, appropriate to the domain e.g. a class/type

        Domain     Meaning of 'kind'
        ------     -----------------
        'C++'      the C++ class
        'python'   the python class
        'cpython'  C structure/type (implementation detail within Python)
        'pyarena'  Python memory allocator

      detail: additional detail
    '''

    def __new__(_cls, domain, kind, detail=None):
        return tuple.__new__(_cls, (domain, kind, detail))

    def __str__(self):
        return '%s:%s:%s' % (self.domain, self.kind, self.detail)

class Usage(object):
    # Information about an in-use area of memory
    slots = ('start', 'size', 'category', 'level', 'hd', 'obj')

    def __init__(self, start, size, category=None, level=None, hd=None, obj=None):
        assert isinstance(start, int)
        assert isinstance(size, int)
        if category:
            assert isinstance(category, Category)
        self.start = start
        self.size = size
        self.category = category
        self.level = level
        self.hd = hd
        self.obj = obj

    def __repr__(self):
        result = 'Usage(%s, %s' % (hex(self.start), hex(self.size))
        if self.category:
            result += ', %r' % (self.category, )
        if self.hd:
            result += ', hd=%r' % self.hd
        if self.obj:
            result += ', obj=%r' % self.obj
        return result + ')'

    def ensure_category(self, usage_set=None):
        if self.category is None:
            self.category = categorize(self, usage_set)

    def ensure_hexdump(self):
        if self.hd is None:
            self.hd = hexdump_as_bytes(self.start, NUM_HEXDUMP_BYTES)


def hexdump_as_bytes(addr, size, chars_only=True):
    addr = gdb.Value(addr).cast(type_unsigned_char_ptr)
    bytebuf = []
    for j in range(size):
        ptr = addr + j
        b = int(ptr.dereference())
        bytebuf.append(b)

    result = ''
    if not chars_only:
        result += ' '.join(['%02x' % b for b in bytebuf]) + ' |'
    result += ''.join([as_hexdump_char(b) for b in bytebuf])
    result += '|'

    return (result)

def hexdump_as_int(addr, count):
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
    return (' '.join([fmt_addr(int) for long in longbuf])
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
        for colIndex in range(self.numcolumns):
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
        self.usage_by_address = dict([(int(u.start), u) for u in usage_list])

    def set_addr_category(self, addr, category, level=0, visited=None, debug=False):
        '''Attempt to mark the given address as being of the given category,
        whilst maintaining a set of address already visited, to try to stop
        infinite graph traveral'''
        if visited:
            if addr in visited:
                if debug:
                    print('addr 0x%x already visited (for category %r)' % (addr, category))
                return False
            visited.add(addr)

        if addr in self.usage_by_address:
            if debug:
                print('addr 0x%x found (for category %r, level=%i)' % (addr, category, level))
            u = self.usage_by_address[addr]
            # Bail if we already have a more detailed categorization for the
            # address:
            if level <= u.level:
                if debug:
                    print ('addr 0x%x already has category %r (level %r)'
                           % (addr, u.category, u.level))
                return False
            u.category = category
            u.level = level
            return True
        else:
            if debug:
                print('addr 0x%x not found (for category %r)' % (addr, category))

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
        self._type_PyCodeObject_ptr = caching_lookup_type('PyCodeObject').pointer()
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
        c = u.category
        if c.domain != 'python':
            return False
        if u.obj:
            if u.obj.categorize_refs(usage_set):
                return True

        if c.kind == 'list':
            list_ptr = gdb.Value(u.start + self._type_PyGC_Head.sizeof).cast(self._type_PyListObject_ptr)
            ob_item = int(list_ptr['ob_item'])
            usage_set.set_addr_category(ob_item,
                                        Category('cpython', 'PyListObject ob_item table', None))
            return True

        elif c.kind == 'set':
            set_ptr = gdb.Value(u.start + self._type_PyGC_Head.sizeof).cast(self._type_PySetObject_ptr)
            table = int(set_ptr['table'])
            usage_set.set_addr_category(table,
                                        Category('cpython', 'PySetObject setentry table', None))
            return True

        if c.kind == 'code':
            # Python 2.6's PyCode_Type doesn't have Py_TPFLAGS_HAVE_GC:
            code_ptr = gdb.Value(u.start).cast(self._type_PyCodeObject_ptr)
            co_code =  int(code_ptr['co_code'])
            usage_set.set_addr_category(co_code,
                                        Category('python', 'str', 'bytecode'), # FIXME: on py3k this should be bytes
                                        level=1)
            return True
        elif c.kind == 'sqlite3.Statement':
            ptr_type = caching_lookup_type('pysqlite_Statement').pointer()
            obj_ptr = gdb.Value(u.start).cast(ptr_type)
            #print obj_ptr.dereference()
            from heap.sqlite import categorize_sqlite3
            for fieldname, catname, fn in (('db', 'sqlite3', categorize_sqlite3),
                                           ('st', 'sqlite3_stmt', None)):
                field_ptr = int(obj_ptr[fieldname])

                # sqlite's src/mem1.c adds a a sqlite3_int64 (size) to the front
                # of the allocation, so we need to look 8 bytes earlier to find
                # the malloc-ed region:
                malloc_ptr = field_ptr - 8

                # print u, fieldname, category, field_ptr
                if usage_set.set_addr_category(malloc_ptr, Category('sqlite3', catname)):
                    if fn:
                        fn(field_ptr, usage_set, set())
            return True

        elif c.kind == 'rpm.hdr':
            ptr_type = caching_lookup_type('struct hdrObject_s').pointer()
            if ptr_type:
                obj_ptr = gdb.Value(u.start).cast(ptr_type)
                # print obj_ptr.dereference()
                h = obj_ptr['h']
                if usage_set.set_addr_category(int(h), Category('rpm', 'Header', None)):
                    blob = h['blob']
                    usage_set.set_addr_category(int(blob), Category('rpm', 'Header blob', None))

        elif c.kind == 'rpm.mi':
            ptr_type = caching_lookup_type('struct rpmmiObject_s').pointer()
            if ptr_type:
                obj_ptr = gdb.Value(u.start).cast(ptr_type)
                print(obj_ptr.dereference())
                mi = obj_ptr['mi']
                if usage_set.set_addr_category(int(mi),
                                               Category('rpm', 'rpmdbMatchIterator', None)):
                    pass
                    #blob = h['blob']
                    #usage_set.set_addr_category(int(blob), 'rpm Header blob')

        # Not categorized:
        return False

def _get_register_state():
    from heap.compat import execute
    return execute('thread apply all info registers')

__cached_usage_list = None
__cached_reg_state = None

def lazily_get_usage_list():
    '''Lazily do a full-graph categorization, getting a list of Usage instances'''
    global __cached_usage_list
    global __cached_reg_state

    reg_state = _get_register_state()
    # print 'reg_state', reg_state
    if __cached_usage_list and __cached_reg_state:
        # Verify that the inferior process hasn't changed state since the cache
        # was populated.
        # Something of a hack: verify that all registers have the same values:
        if reg_state == __cached_reg_state:
            # We can use the cache:
            # print 'USING THE CACHE'
            return __cached_usage_list

    # print 'REGENERATING THE CACHE'

    # Do the work:
    usage_list = list(iter_usage_with_progress())
    categorize_usage_list(usage_list)

    # Update the cache:
    __cached_usage_list = usage_list
    __cached_reg_state = reg_state

    return __cached_usage_list

def categorize_usage_list(usage_list):
    '''Do a "full-graph" categorization of the given list of Usage instances
    For example, if p is a (PyDictObject*), then mark p->ma_table and p->ma_mask
    accordingly
    '''
    usage_set = UsageSet(usage_list)
    visited = set()

    # Precompute some types, if available:
    pycategorizer = PythonCategorizer.make()

    for u in ProgressNotifier(iter(usage_list), 'Blocks analyzed'):
        # Cover the simple cases, where the category can be figured out directly:
        u.ensure_category(usage_set)

        # Cross-references:
        if u.obj:
            if u.obj.categorize_refs(usage_set):
                continue

        # Try to categorize buffers used by python objects:
        if pycategorizer:
            if pycategorizer.categorize(u, usage_set):
                continue

    from heap.cpython import python_categorization
    python_categorization(usage_set)


def categorize(u, usage_set):
    '''Given an in-use block, try to guess what it's being used for
    If usage_set is provided, this categorization may lead to further
    categorizations'''
    from heap.cpython import as_python_object, obj_addr_to_gc_addr
    addr, size = u.start, u.size
    pyop = as_python_object(addr)
    if pyop:
        u.obj = pyop
        try:
            return pyop.categorize()
        except (RuntimeError, UnicodeEncodeError, UnicodeDecodeError):
            # If something went wrong, assume that this wasn't really a python
            # object, and fall through:
            print("couldn't categorize pyop:", pyop)
            pass

    # PyPy detection:
    from heap.pypy import pypy_categorizer
    cat = pypy_categorizer(addr, size)
    if cat:
        return cat

    # C++ detection: only enabled if we can capture "execute"; there seems to
    # be a bad interaction between pagination and redirection: all output from
    # "heap" disappears in the fallback form of execute, unless we "set pagination off"
    from heap.compat import has_gdb_execute_to_string
    #  Disable for now, see https://bugzilla.redhat.com/show_bug.cgi?id=620930
    if False: # has_gdb_execute_to_string:
        from heap.cplusplus import get_class_name
        cpp_cls = get_class_name(addr, size)
        if cpp_cls:
            return Category('C++', cpp_cls)

    # GObject detection:
    from heap.gobject import as_gtype_instance
    ginst = as_gtype_instance(addr, size)
    if ginst:
        u.obj = ginst
        return ginst.categorize()

    s = as_nul_terminated_string(addr, size)
    if s and len(s) > 2:
        return Category('C', 'string data')

    # Uncategorized:
    return Category('uncategorized', '', '%s bytes' % size)

def as_nul_terminated_string(addr, size):
    # Does this look like a NUL-terminated string?
    ptr = gdb.Value(addr).cast(type_char_ptr)
    try:
        s = ptr.string(encoding='ascii')
        return s
    except (RuntimeError, UnicodeDecodeError):
        # Probably not string data:
        return None

class ProgressNotifier(object):
    '''Wrap an iterable with progress notification to stdout'''
    def __init__(self, inner, msg):
        self.inner = inner
        self.count = 0
        self.msg = msg

    def __iter__(self):
        return self

    def __next__(self):
        self.count += 1
        if 0 == self.count % 10000:
            print(self.msg, self.count)
        return self.inner.__next__()



def iter_usage_with_progress():
    return ProgressNotifier(iter_usage(), 'Blocks retrieved')


class CachedInferiorState(object):
    """
    Cached state containing information scraped from the inferior process
    """
    def __init__(self):
        self._arena_detectors = []

    def add_arena_detector(self, detector):
        self._arena_detectors.append(detector)

    def detect_arena(self, ptr, chunksize):
        '''Detect if this ptr returned by malloc is in use by any of the
        layered allocation schemes, returning arena object if it is, None
        if not'''
        for detector in self._arena_detectors:
            arena = detector.as_arena(ptr, chunksize)
            if arena:
                return arena

        # Not found:
        return None


def iter_usage():
    # Iterate through glibc, and within that, within Python arena blocks, as appropriate
    from heap.glibc import glibc_arenas
    ms = glibc_arenas.get_ms()

    cached_state = CachedInferiorState()

    from heap.cpython import ArenaDetection as CPythonArenaDetection, PyArenaPtr, ArenaObject
    try:
        cpython_arenas = CPythonArenaDetection()
        cached_state.add_arena_detector(cpython_arenas)
    except WrongInferiorProcess:
        pass

    from heap.pypy import ArenaDetection as PyPyArenaDetection
    try:
        pypy_arenas = PyPyArenaDetection()
        cached_state.add_arena_detector(pypy_arenas)
    except WrongInferiorProcess:
        pass

    for i, chunk in enumerate(ms.iter_mmap_chunks()):
        mem_ptr = chunk.as_mem()
        chunksize = chunk.chunksize()

        arena = cached_state.detect_arena(mem_ptr, chunksize)
        if arena:
            for u in arena.iter_usage():
                yield u
        else:
            yield Usage(int(mem_ptr), chunksize)

    for chunk in ms.iter_sbrk_chunks():
        mem_ptr = chunk.as_mem()
        chunksize = chunk.chunksize()

        if chunk.is_inuse():
            arena = cached_state.detect_arena(mem_ptr, chunksize)
            if arena:
                for u in arena.iter_usage():
                    yield u
            else:
                yield Usage(int(mem_ptr), chunksize)



def looks_like_ptr(value):
    '''Does this gdb.Value pointer's value looks reasonable?

    For use when casting a block of memory to a structure on pointer fields
    within that block of memory.
    '''

    # NULL is acceptable; assume that it's 0 on every arch we care about
    if value == 0:
        return True

    # Assume that pointers aren't allocated in the bottom 1MB of a process'
    # address space:
    if value < (1024 * 1024):
        return False

    # Assume that if it got this far, that it's valid:
    return True
