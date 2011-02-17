import gdb
from heap import WrappedPointer, caching_lookup_type, Usage, \
    type_void_ptr, fmt_addr, Category, looks_like_ptr, \
    WrongInferiorProcess

def pypy_categorizer(addr, size):
    return None

class ArenaCollection(WrappedPointer):

    # Corresponds to pypy/rpython/memory/gc/minimarkpage.py:ArenaCollection

    def get_arenas(self):
        # Yield a sequence of (struct pypy_ArenaReference0*) gdb.Value instances
        # representing the arenas
        current_arena = self.field('ac_inst_current_arena')
        # print "self.field('ac_inst_current_arena'): %s" % self.field('ac_inst_current_arena')
        if current_arena:
            yield ArenaReference(current_arena)
        # print "self.field('ac_inst_arenas_lists'):%s" % self.field('ac_inst_arenas_lists')
        #for arena in :
        arena = self.field('ac_inst_arenas_lists')
        #while arena:
        #    yield ArenaReference(arena)
        #    arena = arena.dereference()['ac_inst_nextarena']
        
class ArenaReference(WrappedPointer):
    def iter_usage(self):
        # print 'got PyPy arena within allocations'
        return [] # FIXME
    
class ArenaDetection(object):
    '''Detection of PyPy arenas, done as an object so that we can cache state'''
    def __init__(self):
        try:
            ac_global = gdb.parse_and_eval('pypy_g_pypy_rpython_memory_gc_minimarkpage_ArenaCollect')
        except RuntimeError:
            # Not PyPy?
            raise WrongInferiorProcess('pypy')
        self._ac = ArenaCollection(ac_global.address)
        self._arena_refs = []
        self._malloc_ptrs = {}
        for ar in self._ac.get_arenas():
            print ar
            print ar._gdbval.dereference()
            self._arena_refs.append(ar)
            # ar_base : address as returned by malloc
            self._malloc_ptrs[long(ar.field('ar_base'))] = ar
        print self._malloc_ptrs

    def as_arena(self, ptr, chunksize):
        if ptr in self._malloc_ptrs:
            return self._malloc_ptrs[ptr]
        return None
