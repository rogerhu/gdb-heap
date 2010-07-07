'''
gdb 7 hooks for glibc's heap implementation

See /usr/src/debug/glibc-*/malloc/
e.g. /usr/src/debug/glibc-2.11.1/malloc/malloc.h and /usr/src/debug/glibc-2.11.1/malloc/malloc.c
'''

import gdb
import re
import datetime
import sys

# We defer most type lookups to when they're needed, since they'll fail if the
# DWARF data for the relevant DSO hasn't been loaded yet, which is typically
# the case for an executable dynamically linked against glibc

_type_void_ptr = gdb.lookup_type('void').pointer()
_type_char_ptr = gdb.lookup_type('char').pointer()
_type_unsigned_char_ptr = gdb.lookup_type('unsigned char').pointer()

_type_cache = {}

def caching_lookup_type(typename):
    '''Adds caching to gdb.lookup_type(), whilst still raising RuntimeError if
    the type isn't found.'''
    if typename in _type_cache:
        gdbtype = _type_cache[typename]
        if gdbtype:
            return gdbtype
        raise RuntimeError('(cached) Could not find type "%s"' % typename)
    try:
        gdbtype = gdb.lookup_type(typename)
    except RuntimeError, e:
        # did not find the type: add a None to the cache
        gdbtype = None
    _type_cache[typename] = gdbtype
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
#        return long(self._gdbval.cast(_type_void_ptr))

    def is_null(self):
        return long(self._gdbval) == 0

class WrappedPointer(WrappedValue):
    def as_address(self):
        return long(self._gdbval.cast(_type_void_ptr))

    def __str__(self):
        return ('<%s for inferior 0x%x>'
                % (self.__class__.__name__,
                   self.as_address()
                   )
                )

class MChunkPtr(WrappedPointer):
    '''Wrapper around glibc's mchunkptr
    
    Note:
      as_address() gives the address of the chunk as seen by the malloc implementation
      as_mem() gives the address as seen by the user of malloc'''

    # size field is or'ed with PREV_INUSE when previous adjacent chunk in use
    PREV_INUSE = 0x1

    # /* extract inuse bit of previous chunk */
    # #define prev_inuse(p)       ((p)->size & PREV_INUSE)


    # size field is or'ed with IS_MMAPPED if the chunk was obtained with mmap()
    IS_MMAPPED = 0x2

    # /* check for mmap()'ed chunk */
    # #define chunk_is_mmapped(p) ((p)->size & IS_MMAPPED)


    # size field is or'ed with NON_MAIN_ARENA if the chunk was obtained
    # from a non-main arena.  This is only set immediately before handing
    # the chunk to the user, if necessary.
    NON_MAIN_ARENA = 0x4

    # /* check for chunk from non-main arena */
    # #define chunk_non_main_arena(p) ((p)->size & NON_MAIN_ARENA)

    SIZE_BITS = (PREV_INUSE|IS_MMAPPED|NON_MAIN_ARENA)

    @classmethod
    def gdb_type(cls):
        # Deferred lookup of the "mchunkptr" type:
        return caching_lookup_type('mchunkptr')

    def size(self):
        if not(hasattr(self, '_cached_size')):
            self._cached_size = long(self.field('size'))
        return self._cached_size

    def chunksize(self):
        return self.size() & ~(self.SIZE_BITS)

    def has_flag(self, flag):
        return self.size() & flag

    def has_PREV_INUSE(self):
        return self.has_flag(self.PREV_INUSE)

    def has_IS_MMAPPED(self):
        return self.has_flag(self.IS_MMAPPED)

    def has_NON_MAIN_ARENA(self):
        return self.has_flag(self.NON_MAIN_ARENA)

    def __str__(self):
        result = ('<%s chunk=0x%x mem=0x%x' 
                  % (self.__class__.__name__,
                     self.as_address(),
                     self.as_mem()))
        if self.has_PREV_INUSE():
            result += ' PREV_INUSE'
        else:
            result += ' prev_size=%i' % self.field('prev_size')
        if self.has_NON_MAIN_ARENA():
            result += ' NON_MAIN_ARENA'
        if self.has_IS_MMAPPED():
            result += ' IS_MMAPPED'
        else:
            if self.is_inuse():
                result += ' inuse'
            else:
                result += ' free'
        SIZE_SZ = caching_lookup_type('size_t').sizeof
        result += ' chunksize=%i memsize=%i>' % (self.chunksize(),
                                                 self.chunksize() - (2 * SIZE_SZ))
        return result

    def as_mem(self):
        # Analog of chunk2mem: the address as seen by the program (e.g. malloc)
        SIZE_SZ = caching_lookup_type('size_t').sizeof
        return self.as_address() + (2 * SIZE_SZ)

    def is_inuse(self):
        # Is this chunk is use?
        if self.has_IS_MMAPPED():
            return True
        # Analog of #define inuse(p)
        #   ((((mchunkptr)(((char*)(p))+((p)->size & ~SIZE_BITS)))->size) & PREV_INUSE)
        nc = self.next_chunk()
        return nc.has_PREV_INUSE()
        
    def next_chunk(self):
        # Analog of:
        #   #define next_chunk(p) ((mchunkptr)( ((char*)(p)) + ((p)->size & ~SIZE_BITS) ))
        ptr = self._gdbval.cast(_type_char_ptr)
        cs = self.chunksize()
        ptr += cs
        ptr = ptr.cast(MChunkPtr.gdb_type())
        #print 'next_chunk returning: 0x%x' % ptr
        return MChunkPtr(ptr)

    def prev_chunk(self):
        # Analog of:
        #   #define prev_chunk(p) ((mchunkptr)( ((char*)(p)) - ((p)->prev_size) ))
        ptr = self._gdbval.cast(_type_char_ptr)
        ptr -= self.field('prev_size')
        ptr = ptr.cast(MChunkPtr.gdb_type())
        return MChunkPtr(ptr)

class MBinPtr(MChunkPtr):
    # Wrapper around an "mbinptr"

    @classmethod
    def gdb_type(cls):
        # Deferred lookup of the "mbinptr" type:
        return caching_lookup_type('mbinptr')

    def first(self):
        return MChunkPtr(self.field('fd'))

    def last(self):
        return MChunkPtr(self.field('bk'))

class MFastBinPtr(MChunkPtr):
    # Wrapped around a mfastbinptr
    pass

class MallocState(WrappedValue):
    # Wrapper around struct malloc_state, as defined in malloc.c

    def fastbin(self, idx):
        return MFastBinPtr(self.field('fastbinsY')[idx])

    def bin_at(self, i):
        # addressing -- note that bin_at(0) does not exist
        #  (mbinptr) (((char *) &((m)->bins[((i) - 1) * 2]))
        #	     - offsetof (struct malloc_chunk, fd))

        ptr = self.field('bins')[(i-1)*2]
        #print '001', ptr
        ptr = ptr.address
        #print '002', ptr
        ptr = ptr.cast(_type_char_ptr)
        #print '003', ptr
        ptr -= offsetof('struct malloc_chunk', 'fd')
        #print '004', ptr
        ptr = ptr.cast(MBinPtr.gdb_type())
        #print '005', ptr
        return MBinPtr(ptr)

    def iter_chunks(self):
        '''Yield a sequence of MChunkPtr corresponding to all chunks of memory
        in the heap (both used and free), in order of ascending address'''

        for c in self.iter_mmap_chunks():
            yield c

        for c in self.iter_sbrk_chunks():
            yield c

    def iter_mmap_chunks(self):
        for inf in gdb.inferiors():
            for (start, end) in iter_mmap_heap_chunks(inf.pid):
                # print "Trying 0x%x-0x%x" % (start, end)
                try:
                    chunk = MChunkPtr(gdb.Value(start).cast(MChunkPtr.gdb_type()))
                    # Does this look like the first chunk within a range of
                    # mmap address space?
                    #print ('0x%x' % chunk.as_address() + chunk.chunksize())
                    if (not chunk.has_NON_MAIN_ARENA() and chunk.has_IS_MMAPPED()
                        and chunk.as_address() + chunk.chunksize() <= end):

                        # Iterate upwards until you reach "end" of mmap space:
                        while chunk.as_address() < end and chunk.has_IS_MMAPPED():
                            yield chunk
                            # print '0x%x' % chunk.as_address(), chunk
                            chunk = chunk.next_chunk()
                except RuntimeError:
                    pass

    def iter_sbrk_chunks(self):
        '''Yield a sequence of MChunkPtr corresponding to all chunks of memory
        in the heap (both used and free), in order of ascending address, for those
        from sbrk_base upwards'''
        # FIXME: this is currently a hack; I need to verify my logic here

        # As I understand it, it's only possible to navigate the following ways:
        #
        # For a chunk with PREV_INUSE:0, then prev_size is valid, and can be used
        # to substract down to the start of that chunk
        # For a chunk with PREV_INUSE:1, then prev_size is not readable (reading it
        # could lead to SIGSEGV), and it's not possible to get at the size of the
        # previous chunk.

        # For a free chunk, we have next/prev pointers to a doubly-linked list
        # of other free chunks.

        # For a chunk, we have the size, and that size gives us the address of the next chunk in RAM
        # So if we know the address of the first chunk, then we can use this to iterate upwards through RAM,
        # and thus iterate over all of the chunks

        # Start at "mp_.sbrk_base"
        chunk = MChunkPtr(gdb.Value(sbrk_base()).cast(MChunkPtr.gdb_type()))
        # sbrk_base is NULL when no small allocations have happened:
        if chunk.as_address() > 0:
            # Iterate upwards until you reach "top":
            top = long(self.field('top'))
            while chunk.as_address() != top:
                yield chunk
                # print '0x%x' % chunk.as_address(), chunk
                try:
                    chunk = chunk.next_chunk()
                except RuntimeError:
                    break




    def iter_free_chunks(self):
        '''Yield a sequence of MChunkPtr (some of which may be MFastBinPtr),
        corresponding to the free chunks of memory'''
        # Account for top:
        print 'top'
        yield MChunkPtr(self.field('top'))

        NFASTBINS = self.NFASTBINS()
        # Traverse fastbins:
        for i in xrange(0, NFASTBINS):
            print 'fastbin %i' % i
            p = self.fastbin(i)
            while not p.is_null():
                # FIXME: untested
                yield MChunkPtr(p)
                p = p.field('fd') # FIXME: wrap
                
        #   for (p = fastbin (av, i); p != 0; p = p->fd) {
        #     ++nfastblocks;
        #     fastavail += chunksize(p);
        #   }
        # }

        # Must keep this in-sync with malloc.c:
        # FIXME: can we determine this dynamically from within gdb?
        NBINS = 128

        # Traverse regular bins:
        for i in xrange(1, NBINS):
            print 'regular bin %i' % i
            b = self.bin_at(i)
            #print 'b: %s' % b
            p = b.last()
            n = 0
            #print 'p:', p
            while p.as_address() != b.as_address():
                #print 'n:', n
                #print 'b:', b
                #print 'p:', p
                n+=1
                yield p
                p = MChunkPtr(p.field('bk'))
        #    for (p = last(b); p != b; p = p->bk) {
        #        ++nblocks;
        #          avail += chunksize(p);
        #    }
        # }

    def NFASTBINS(self):
        fastbinsY = self.field('fastbinsY')
        return array_length(fastbinsY)

class MallocPar(WrappedValue):
    # Wrapper around static struct malloc_par mp_
    @classmethod
    def get(cls):
        # It's a singleton:
        gdbval = gdb.parse_and_eval('mp_')
        return MallocPar(gdbval)

def sbrk_base():
    mp_ = MallocPar.get()
    #print mp_
    return long(mp_.field('sbrk_base'))


"""
"""


# See malloc.c:
#    struct mallinfo mALLINFo(mstate av)
#    {
#      struct mallinfo mi;
#      size_t i;
#      mbinptr b;
#      mchunkptr p;
#      INTERNAL_SIZE_T avail;
#      INTERNAL_SIZE_T fastavail;
#      int nblocks;
#      int nfastblocks;
#    
#      /* Ensure initialization */
#      if (av->top == 0)  malloc_consolidate(av);
#    
#      check_malloc_state(av);
#    
#      /* Account for top */
#      avail = chunksize(av->top);
#      nblocks = 1;  /* top always exists */
#    
#      /* traverse fastbins */
#      nfastblocks = 0;
#      fastavail = 0;
#    
#      for (i = 0; i < NFASTBINS; ++i) {
#        for (p = fastbin (av, i); p != 0; p = p->fd) {
#          ++nfastblocks;
#          fastavail += chunksize(p);
#        }
#      }
#    
#      avail += fastavail;
#    
#      /* traverse regular bins */
#      for (i = 1; i < NBINS; ++i) {
#        b = bin_at(av, i);
#        for (p = last(b); p != b; p = p->bk) {
#          ++nblocks;
#          avail += chunksize(p);
#        }
#      }
#    
#      mi.smblks = nfastblocks;
#      mi.ordblks = nblocks;
#      mi.fordblks = avail;
#      mi.uordblks = av->system_mem - avail;
#      mi.arena = av->system_mem;
#      mi.hblks = mp_.n_mmaps;
#      mi.hblkhd = mp_.mmapped_mem;
#      mi.fsmblks = fastavail;
#      mi.keepcost = chunksize(av->top);
#      mi.usmblks = mp_.max_total_mem;
#      return mi;
#    }
#    

def fmt_addr(addr):
    # FIXME: this assumes 64-bit
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

def iter_mmap_heap_chunks(pid):
    '''Try to locate the memory-mapped heap allocations for the given
    process (by PID) by reading /proc/PID/maps
    
    Yield a sequence of (start, end) pairs'''
    for line in open('/proc/%i/maps' % pid):
        # print line,
        # e.g.:
        # 38e441e000-38e441f000 rw-p 0001e000 fd:01 1087                           /lib64/ld-2.11.1.so
        # 38e441f000-38e4420000 rw-p 00000000 00:00 0
        hexd = r'[0-9a-f]'
        hexdigits = '(' + hexd + '+)'
        m = re.match(hexdigits + '-' + hexdigits
                     + r' ([r\-][w\-][x\-][ps]) ' + hexdigits
                     + r' (..:..) (\d+)\s+(.*)',
                     line)
        if m:
            # print m.groups()
            start, end, perms, offset, dev, inode, pathname = m.groups()
            # PROT_READ, PROT_WRITE, MAP_PRIVATE:
            if perms == 'rw-p':
                if offset == '00000000': # FIXME bits?
                    if dev == '00:00': # FIXME
                        if inode == '0': # FIXME
                            if pathname == '': # FIXME
                                # print 'heap line?:', line
                                # print m.groups()
                                start, end = [int(m.group(i), 16) for i in (1, 2)]
                                yield (start, end)
        else:
            print 'unmatched :', line


def get_ms():
    val_main_arena = gdb.parse_and_eval('main_arena')
    ms = MallocState(val_main_arena)
    return ms        

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

class Snapshot(object):
    '''Snapshot of the state of the heap'''
    def __init__(self, name, time):
        self.name = name
        self.time = time
        self._all_usage = set()
        self._totalsize = 0
        self._num_usage = 0

    def _add_usage(self, u):
        self._all_usage.add(u)
        self._totalsize += u.size
        self._num_usage += 1
        return u

    @classmethod
    def current(cls, name):
        result = cls(name, datetime.datetime.now())
        for i, u in enumerate(iter_usage()):
            u.ensure_category()
            u.ensure_hexdump()
            result._add_usage(u)
        return result

    def total_size(self):
        '''Get total allocated size, in bytes'''
        return self._totalsize

    def summary(self):
        return '%s allocated, in %i blocks' % (fmt_size(self.total_size()), 
                                               self._num_usage)

    def size_by_address(self, address):
        return self._chunk_by_address[address].size

class History(object):
    '''History of snapshots of the state of the heap'''
    def __init__(self):
        self.snapshots = []

    def add(self, name):
        s = Snapshot.current(name)
        self.snapshots.append(s)
        return s

class Diff(object):
    '''Differences between two states of the heap'''
    def __init__(self, old, new):
        self.old = old
        self.new = new

        self.new_minus_old = self.new._all_usage - self.old._all_usage
        self.old_minus_new = self.old._all_usage - self.new._all_usage

    def stats(self):
        size_change = self.new.total_size() - self.old.total_size()
        count_change = self.new._num_usage - self.old._num_usage
        return "%s%s bytes, %s%s blocks" % (sign(size_change),
                                      fmt_size(size_change),
                                      sign(count_change),
                                      fmt_size(count_change))
        
    def as_changes(self):
        result = self.chunk_report('Free-d blocks', self.old, self.old_minus_new)
        result += self.chunk_report('New blocks', self.new, self.new_minus_old)
        # FIXME: add changed chunks
        return result

    def chunk_report(self, title, snapshot, set_of_usage):
        result = '%s:\n' % title
        if len(set_of_usage) == 0:
            result += '  (none)\n'
            return result
        for usage in sorted(set_of_usage,
                            lambda u1, u2: cmp(u1.start, u2.start)):
            result += ('  %s -> %s %8i bytes %20s |%s\n'
                       % (fmt_addr(usage.start),
                          fmt_addr(usage.start + usage.size-1),
                          usage.size, usage.category, usage.hd))
        return result
    
history = History()

def hexdump_as_bytes(addr, size):
    addr = gdb.Value(addr).cast(_type_unsigned_char_ptr)
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
        bptr = gdb.Value(ptr).cast(_type_unsigned_char_ptr)
        for i in range(8): # FIXME
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

def categorize_sqlite3(addr, usage_set, visited):
    # "struct sqlite3" is defined in src/sqliteInt.h, which is an internal header
    ptr_type = caching_lookup_type('sqlite3').pointer()    
    obj_ptr = gdb.Value(addr).cast(ptr_type)
    # print obj_ptr.dereference()

    aDb = obj_ptr['aDb']
    Db_addr = long(aDb)
    Db_malloc_addr = Db_addr - 8
    if usage_set.set_addr_category(Db_malloc_addr, 'sqlite3 struct Db', visited):
        print aDb['pBt'].dereference()
        # FIXME

def categorize_usage_list(usage_list):
    '''Do a "full-graph" categorization of the given list of Usage instances
    For example, if p is a (PyDictObject*), then mark p->ma_table and p->ma_mask
    accordingly
    '''
    usage_set = UsageSet(usage_list)
    visited = set()

    # Precompute some types:
    _type_PyDictObject_ptr = caching_lookup_type('PyDictObject').pointer()
    _type_PyListObject_ptr = caching_lookup_type('PyListObject').pointer()
    _type_PySetObject_ptr = caching_lookup_type('PySetObject').pointer()
    _type_PyUnicodeObject_ptr = caching_lookup_type('PyUnicodeObject').pointer()
    _type_PyGC_Head = caching_lookup_type('PyGC_Head')

    for u in usage_list:
        u.ensure_category()
        if u.category == 'python dict':
            dict_ptr = gdb.Value(u.start + _type_PyGC_Head.sizeof).cast(_type_PyDictObject_ptr)
            ma_table = long(dict_ptr['ma_table'])
            usage_set.set_addr_category(ma_table, 'PyDictEntry table')

        elif u.category == 'python list':
            list_ptr = gdb.Value(u.start + _type_PyGC_Head.sizeof).cast(_type_PyListObject_ptr)
            ob_item = long(list_ptr['ob_item'])
            usage_set.set_addr_category(ob_item, 'PyListObject ob_item table')

        elif u.category == 'python set':
            set_ptr = gdb.Value(u.start + _type_PyGC_Head.sizeof).cast(_type_PySetObject_ptr)
            table = long(set_ptr['table'])
            usage_set.set_addr_category(table, 'PySetObject setentry table')

        elif u.category == 'python unicode':
            unicode_ptr = gdb.Value(u.start).cast(_type_PyUnicodeObject_ptr)
            m_str = long(unicode_ptr['str'])
            usage_set.set_addr_category(m_str, 'PyUnicodeObject buffer')

        elif u.category == 'python sqlite3.Statement':
            ptr_type = caching_lookup_type('pysqlite_Statement').pointer()
            obj_ptr = gdb.Value(u.start).cast(ptr_type)
            #print obj_ptr.dereference()
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



class HeapCmd(gdb.Command):
    '''
    '''
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap",
                              gdb.COMMAND_DATA)
        self.subcmds = ['all', 'used', 'log', 'label', 'sizes', 'diff']
        
    def complete(self, text, word):
        # print "complete: %r %r" % (text, word)
        args = text.split()
        # print 'args: %r' % args
        if len(args) == 0:
            return self.subcmds
        if len(args) == 1:
            return [subcmd for subcmd in self.subcmds if subcmd.startswith(args[0])]

    def print_used_memory_by_category(self):
        total_by_category = {}
        count_by_category = {}
        total_size = 0
        total_count = 0
        try:
            usage_list = list(iter_usage())
            categorize_usage_list(usage_list)
            for u in usage_list:
                u.ensure_category()
                if u.category == 'uncategorized data':
                    u.category += ' (%s bytes)' % u.size
                total_size += u.size
                if u.category in total_by_category:
                    total_by_category[u.category] += u.size
                else:
                    total_by_category[u.category] = u.size

                total_count += 1
                if u.category in count_by_category:
                    count_by_category[u.category] += 1
                else:
                    count_by_category[u.category] = 1
                    
        except KeyboardInterrupt:
            pass # FIXME

        t = Table(['Category', 'Count', 'Allocated size'])
        for category in sorted(total_by_category.keys(),
                               lambda s1, s2: cmp(total_by_category[s2],
                                                  total_by_category[s1])
                               ):
            t.add_row([category, 
                       fmt_size(count_by_category[category]),
                       fmt_size(total_by_category[category])])
        t.add_row(['TOTAL', fmt_size(total_count), fmt_size(total_size)])
        t.write(sys.stdout)
        print

    def print_used_chunks_by_size(self):
        ms = get_ms()
        chunks_by_size = {}
        num_chunks = 0
        total_size = 0
        try:
            for chunk in ms.iter_chunks():
                if not chunk.is_inuse():
                    continue
                size = int(chunk.chunksize())
                num_chunks += 1
                total_size += size
                if size in chunks_by_size:
                    chunks_by_size[size] += 1
                else:
                    chunks_by_size[size] = 1
        except KeyboardInterrupt:
            pass # FIXME
        t = Table(['Chunk size', 'Num chunks', 'Allocated size'])
        for size in sorted(chunks_by_size.keys(),
                           lambda s1, s2: chunks_by_size[s2] * s2 - chunks_by_size[s1] * s1):
            t.add_row([fmt_size(size),
                       chunks_by_size[size],
                       fmt_size(chunks_by_size[size] * size)])
        t.add_row(['TOTALS', num_chunks, fmt_size(total_size)])
        t.write(sys.stdout)
        print        


    def print_used_chunks(self):
        print 'Used chunks of memory on heap'
        print '-----------------------------'
        ms = get_ms()
        for i, chunk in enumerate(ms.iter_chunks()):
            if not chunk.is_inuse():
                continue
            size = chunk.chunksize()
            mem = chunk.as_mem()
            category = categorize(mem, size) # FIXME: this is actually the size of the full chunk, rather than that seen by the program
            hd = hexdump_as_bytes(mem, 32)
            print ('%6i: %s -> %s %8i bytes %20s |%s'
                   % (i, 
                      fmt_addr(chunk.as_mem()), 
                      fmt_addr(chunk.as_mem()+size-1), 
                      size, category, hd))
        print

    def print_all_chunks(self):
        print 'All chunks of memory on heap (both used and free)'
        print '-------------------------------------------------'
        ms = get_ms()
        for i, chunk in enumerate(ms.iter_chunks()):
            size = chunk.chunksize()
            if chunk.is_inuse():
                kind = ' inuse'
            else:
                kind = ' free'
            
            print ('%i: %s -> %s %s: %i bytes (%s)'
                   % (i, 
                      fmt_addr(chunk.as_address()),
                      fmt_addr(chunk.as_address()+size-1),
                      kind, size, chunk))
        print

    def impl_log(self):
        h = history
        if len(h.snapshots) == 0:
            print '(no history)'
            return
        for i in xrange(len(h.snapshots), 0, -1):
            s = h.snapshots[i-1]
            print 'Label %i "%s" at %s' % (i, s.name, s.time)
            print '    ', s.summary()
            if i > 1:
                prev = h.snapshots[i-2]
                d = Diff(prev, s)
                print
                print '    ', d.stats()
            print

    def impl_label(self, args):
        s = history.add(args)
        print s.summary()

    def subcmd_diff(self):
        h = history
        if len(h.snapshots) == 0:
            print '(no history)'
            return
        prev = h.snapshots[-1]
        curr = Snapshot.current('current')
        d = Diff(prev, curr)
        print 'Changes from %s to %s' % (prev.name, curr.name)
        print '  ', d.stats()
        print
        print '\n'.join(['  ' + line for line in d.as_changes().splitlines()])


    def invoke(self, args, from_tty):
        # print '"heap" invoked with %r' % args
        #val_main_arena = gdb.parse_and_eval('main_arena')
        #print(val_main_arena)
        #print "sbrk_base: 0x%x" % sbrk_base()

        #for inf in gdb.inferiors():
        #    #print inf
        #    #print 'PID:', inf.pid
        #    #print ['0x%x-0x%x' % (start, end) for start, end in iter_mmap_heap_chunks(inf.pid)]


        #ms = MallocState(val_main_arena)
        #for i, chunk in enumerate(ms.iter_chunks()):
        #    print '%i: 0x%x, %s' % (i, chunk.as_address(), chunk)
        args = args.split()
        if len(args) == 0:
            self.print_used_memory_by_category()
            return

        subcmd = args[0]
        if subcmd == 'all':
            self.print_all_chunks()
        elif subcmd == 'used':
            self.print_used_chunks()
        elif subcmd == 'log':
            self.impl_log()
        elif subcmd == 'label':
            self.impl_label(args[1])
        elif subcmd == 'sizes':
            self.print_used_chunks_by_size()
        elif subcmd == 'diff':
            self.subcmd_diff()
        else:
            print 'Unrecognized heap subcommand "%s"' % subcmd

# ...and register the command:
HeapCmd()

class HexdumpCmd(gdb.Command):
    '''
    '''
    def __init__(self):
        gdb.Command.__init__ (self,
                              "hexdump",
                              gdb.COMMAND_DATA)

    def invoke(self, args, from_tty):
        print repr(args)
        if args.startswith('0x'):
            addr = int(args, 16)
        else:
            addr = int(args)            
            
        # assume that paging will cut in and the user will quit at some point:
        size = 32
        while True:
            hd = hexdump_as_bytes(addr, size)
            print ('%s -> %s %s' % (addr,  addr + size -1, hd))
            addr += size

HexdumpCmd()

# Transliteration from Python's obmalloc.c:
ALIGNMENT             = 8	
ALIGNMENT_SHIFT       = 3
ALIGNMENT_MASK        = (ALIGNMENT - 1)

# Return the number of bytes in size class I:
def INDEX2SIZE(I):
    return (I + 1) << ALIGNMENT_SHIFT

SYSTEM_PAGE_SIZE      = (4 * 1024)
SYSTEM_PAGE_SIZE_MASK = (SYSTEM_PAGE_SIZE - 1)
ARENA_SIZE            = (256 << 10)
POOL_SIZE             = SYSTEM_PAGE_SIZE
POOL_SIZE_MASK        = SYSTEM_PAGE_SIZE_MASK
def ROUNDUP(x):
    return (x + ALIGNMENT_MASK) & ~ALIGNMENT_MASK

def POOL_OVERHEAD():
    return ROUNDUP(caching_lookup_type('struct pool_header').sizeof)

class PyArenaPtr(WrappedPointer):
    # Wrapper around a (void*) that's a Python arena's buffer (the
    # arena->address, as opposed to the (struct arena_object*) itself)
    @classmethod
    def from_addr(cls, p):
        ptr = gdb.Value(p)
        ptr = ptr.cast(_type_void_ptr)
        return cls(ptr)

    #def __init__(self):

    def iter_pools(self):
        '''Yield a sequence of PyPoolPtr, representing all of the pools within
        this arena'''
        # obmalloc.c sets up arenaobj->pool_address to the first pool address, aligning it to POOL_SIZE_MASK 
        initial_pool_addr = self.as_address()
        num_pools = ARENA_SIZE / POOL_SIZE
        excess = initial_pool_addr & POOL_SIZE_MASK
        if excess != 0:
            num_pools -= 1
            initial_pool_addr += POOL_SIZE - excess

        # print 'num_pools:', num_pools
        pool_addr = initial_pool_addr
        for idx in xrange(num_pools):
            pool = PyPoolPtr.from_addr(pool_addr)
            yield pool
            pool_addr += POOL_SIZE

    def iter_usage(self):
        '''Yield a series of Usage instances'''
        initial_pool_addr = self.as_address()
        excess = initial_pool_addr & POOL_SIZE_MASK
        if excess != 0:
            yield Usage(initial_pool_addr, excess, 'python arena alignment wastage')

        for pool in self.iter_pools():
            for u in pool.iter_usage():
                yield u
        

class PyPoolPtr(WrappedPointer):
    # Wrapper around Python's obmalloc.c: poolp: (struct pool_header *)

    @classmethod
    def from_addr(cls, p):
        ptr = gdb.Value(p)
        ptr = ptr.cast(cls.gdb_type())
        return cls(ptr)

    def __str__(self):
        return ('PyPoolPtr([0x%x->0x%x: %d blocks of size %i bytes))'
                % (self.as_address(), self.as_address() + POOL_SIZE,
                   self.num_blocks(), self.block_size()))
        
    @classmethod
    def gdb_type(cls):
        # Deferred lookup of the "poolp" type:
        return caching_lookup_type('poolp')

    def block_size(self):
        return INDEX2SIZE(self.field('szidx'))

    def num_blocks(self):
        firstoffset = self._firstoffset()
        maxnextoffset = self._maxnextoffset()
        offsetrange = maxnextoffset - firstoffset
        return offsetrange / self.block_size() # FIXME: not exactly correctly

    def _firstoffset(self):
        return POOL_OVERHEAD()

    def _maxnextoffset(self):
        return POOL_SIZE - self.block_size()
        
    def iter_blocks(self):
        '''Yield all blocks within this pool, whether free or in use'''
        size = self.block_size()
        maxnextoffset = self._maxnextoffset()
        # print initnextoffset, maxnextoffset        
        offset = self._firstoffset()
        base_addr = self.as_address()
        while offset <= maxnextoffset:
            yield (base_addr + offset, size)
            offset += size

    def iter_usage(self):
        # The struct pool_header at the front:
        yield Usage(self.as_address(),
                    POOL_OVERHEAD(),
                    'python pool_header overhead')

        fb = list(self.iter_free_blocks())
        for (start, size) in fb:
            yield Usage(start, size, 'python freed pool chunk')

        for (start, size) in self.iter_used_blocks():
            if (start, size) not in fb:
                yield Usage(start, size) #, 'python pool: ' + categorize(start, size))

        # FIXME: yield any wastage at the end

    def iter_free_blocks(self):
        '''Yield the sequence of free blocks within this pool.  Doesn't include
        the areas after nextoffset that have never been allocated'''
        size = self.block_size()
        freeblock = self.field('freeblock')
        _type_block_ptr_ptr = caching_lookup_type('unsigned char').pointer().pointer()
        # Walk the singly-linked list of free blocks for this chunk
        while long(freeblock) != 0:
            yield (long(freeblock), long(size))
            freeblock = freeblock.cast(_type_block_ptr_ptr).dereference()

    def _free_blocks(self):
        # Get the set of addresses of free blocks
        return set([addr for addr, size in self.iter_free_blocks()])

    def iter_used_blocks(self):
        '''Yield the sequence of currently in-use blocks within this pool'''
        # We'll filter out the free blocks from the list:
        free_block_addresses = self._free_blocks()

        size = self.block_size()
        initnextoffset = self._firstoffset()
        nextoffset = self.field('nextoffset')
        #print initnextoffset, nextoffset
        offset = initnextoffset
        base_addr = self.as_address()
        # Iterate upwards until you reach "pool->nextoffset": blocks beyond
        # that point have never been allocated:
        while offset < nextoffset:
            addr = base_addr + offset
            # Filter out those within this pool's linked list of free blocks:
            if long(addr) not in free_block_addresses:
                yield (long(addr), long(size))
            offset += size


def categorize(addr, size):
    '''Given an in-use block, try to guess what it's being used for'''
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

    s = as_nul_terminated_string(addr, size)
    if s and len(s) > 2:
        return 'string data'

    # Uncategorized:
    return 'uncategorized data'

def is_pyobject_ptr(addr):
    try:
        _type_pyop = caching_lookup_type('PyObject').pointer()
    except RuntimeError:
        # not linked against python
        return None

    pyop = gdb.Value(addr).cast(_type_pyop)
    try:
        if pyop['ob_refcnt'] < 0xffff:
            if pyop['ob_type']['ob_refcnt'] < 0xffff:
                # Then this looks like a Python object:
                return WrappedPointer(pyop)
    except RuntimeError:
        pass # Not a python object (or corrupt)
    
    # Doesn't look like a python object, implicit return None

def as_python_object(addr):
    '''Given an address of an allocation, determine if it holds a PyObject,
    or a PyGC_Head

    Return a WrappedPointer for the PyObject* if it does (which might have a
    different location c.f. when PyGC_Head was allocated)

    Return None if it doesn't look like a PyObject*'''
    # Try casting to PyObject* ?
    # FIXME: what about the debug allocator?
    try:
        _type_pyop = caching_lookup_type('PyObject').pointer()
    except RuntimeError:
        # not linked against python
        return None
    pyop = is_pyobject_ptr(addr)
    if pyop:
        return pyop
    else:
        # maybe a GC type:
        _type_PyGC_Head = caching_lookup_type('PyGC_Head')
        _type_PyGC_Head_ptr = caching_lookup_type('PyGC_Head').pointer()
        gc_ptr = gdb.Value(addr).cast(_type_PyGC_Head_ptr)
        # print gc_ptr.dereference()
        if gc_ptr['gc']['gc_refs'] == -3: #FIXME: need to cover other values
            pyop = is_pyobject_ptr(gdb.Value(addr + _type_PyGC_Head.sizeof))
            if pyop:
                return pyop
    # Doesn't look like a python object, implicit return None

def as_nul_terminated_string(addr, size):
    # Does this look like a NUL-terminated string?
    ptr = gdb.Value(addr).cast(_type_char_ptr)
    try:
        s = ptr.string(encoding='ascii')
        return s
    except (RuntimeError, UnicodeDecodeError):
        # Probably not string data:
        return None

def python_arena_spelunking():
    # See Python's Objects/obmalloc.c
    ms = get_ms()
    for i, chunk in enumerate(ms.iter_mmap_chunks()):
        if chunk.chunksize() == 266240: #FIXME: 256 * 1024 is 262144 so we're 4100 bytes out (not including chunk overhead)
            print chunk
            # Hopefully we have a python arena's memory
            # Divided into 64 pools of 4k each
            arena_addr = chunk.as_mem()
            print '0x%x' % arena_addr

            arena = PyArenaPtr.from_addr(arena_addr)

            for pool in arena.iter_pools():
                print pool

                print pool._gdbval.dereference()
                #print Pygdb.Value(pool_addr).cast(caching_lookup_type('poolp')).dereference()

                print 'block_size:', pool.block_size()
                #for start, size in pool.iter_blocks():
                #    # is it possible to determine if a block is free/in-use at this level?
                #    # when freed, blocks get added to the head of a per-pool singly-linked list, and so the first sizeof(block*) bytes of such a block are a block* to the next free block in this pool
                #    hd = hexdump_as_long(start, size/8) # FIXME
                #    print '0x%x-0x%x: %s %s' % (start, start+size-1, hd)

                #print 'free blocks:'
                #for start, size in pool.iter_free_blocks():
                #    hd = hexdump_as_long(start, size/8) # FIXME
                #    print '0x%x-0x%x: %s' % (start, start+size-1, hd)

                #print
                print 'used blocks:'
                for start, size in pool.iter_used_blocks():
                    hd = hexdump_as_long(start, size/8) # FIXME
                    print '0x%x-0x%x: %s' % (start, start+size-1, hd)
                    
                    pyop = as_python_object(start)
                    if pyop:
                        print pyop._gdbval
                        # group by type?
                    print categorize(start, size)
                        
def iter_usage():
    ms = get_ms()
    for i, chunk in enumerate(ms.iter_mmap_chunks()):
        # Something of a hack: break down Python arenas by type:
        if chunk.chunksize() == 266240: #FIXME: 256 * 1024 is 262144 so we're 4100 bytes out (not including chunk overhead)
            arena_addr = chunk.as_mem()
            arena = PyArenaPtr.from_addr(arena_addr)
            for u in arena.iter_usage():
                yield u
        else:
            yield Usage(long(chunk.as_mem()), chunk.chunksize())

    for chunk in ms.iter_sbrk_chunks():
        if chunk.is_inuse():
            yield Usage(long(chunk.as_mem()), chunk.chunksize())

            
    


