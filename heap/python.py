'''
This file is licensed under the PSF license
'''
import gdb
from heap import WrappedPointer, caching_lookup_type, Usage, type_void_ptr

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
        ptr = ptr.cast(type_void_ptr)
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

def python_arena_spelunking():
    # See Python's Objects/obmalloc.c
    from heap.glibc import get_ms
    from heap import categorize
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
                        
