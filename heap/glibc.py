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

'''
gdb 7 hooks for glibc's heap implementation

See /usr/src/debug/glibc-*/malloc/
e.g. /usr/src/debug/glibc-2.11.1/malloc/malloc.h and /usr/src/debug/glibc-2.11.1/malloc/malloc.c

This file is licenced under the LGPLv2.1
'''

import re

import gdb

from heap import WrappedPointer, WrappedValue, caching_lookup_type, type_char_ptr

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
        ptr = self._gdbval.cast(type_char_ptr)
        cs = self.chunksize()
        ptr += cs
        ptr = ptr.cast(MChunkPtr.gdb_type())
        #print 'next_chunk returning: 0x%x' % ptr
        return MChunkPtr(ptr)

    def prev_chunk(self):
        # Analog of:
        #   #define prev_chunk(p) ((mchunkptr)( ((char*)(p)) - ((p)->prev_size) ))
        ptr = self._gdbval.cast(type_char_ptr)
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
        ptr = ptr.cast(type_char_ptr)
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
    try:
        return long(mp_.field('sbrk_base'))
    except RuntimeError, e:
        check_missing_debuginfo(e, 'glibc')
        raise e

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

