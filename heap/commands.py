import gdb
import re
import sys

from heap.glibc import get_ms
from heap.history import history, Snapshot, Diff

from heap import iter_usage, \
    fmt_size, fmt_addr, \
    categorize, categorize_usage_list, \
    hexdump_as_bytes, \
    Table

class Heap(gdb.Command):
    'Print a report on memory usage, by category'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap",
                              gdb.COMMAND_DATA,
                              prefix=True)
    def invoke(self, args, from_tty):
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

class HeapSizes(gdb.Command):
    'Print a report on memory usage, by sizes'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap sizes",
                              gdb.COMMAND_DATA)
    def invoke(self, args, from_tty):
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


class HeapUsed(gdb.Command):
    'Print used heap chunks'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap used",
                              gdb.COMMAND_DATA)

    def invoke(self, args, from_tty):
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

class HeapAll(gdb.Command):
    'Print all heap chunks'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap all",
                              gdb.COMMAND_DATA)

    def invoke(self, args, from_tty):
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

class HeapLog(gdb.Command):
    'Print a log of recorded heap states'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap log",
                              gdb.COMMAND_DATA)

    def invoke(self, args, from_tty):
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

class HeapLabel(gdb.Command):
    'Record the current state of the heap for later comparison'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap label",
                              gdb.COMMAND_DATA)

    def invoke(self, args, from_tty):
        s = history.add(args)
        print s.summary()


class HeapDiff(gdb.Command):
    'Compare two states of the heap'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap diff",
                              gdb.COMMAND_DATA)

    def invoke(self, args, from_tty):
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

class Hexdump(gdb.Command):
    'Print a hexdump, starting at the specific region of memory'
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
            print ('%s -> %s %s' % (fmt_addr(addr),  fmt_addr(addr + size -1), hd))
            addr += size


def register_commands():
    # Register the commands with gdb
    Heap()
    HeapSizes()
    HeapUsed()
    HeapAll()
    HeapLog()
    HeapLabel()
    HeapDiff()

    Hexdump()

