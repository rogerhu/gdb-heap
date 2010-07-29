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
            print ('%s -> %s %s' % (fmt_addr(addr),  fmt_addr(addr + size -1), hd))
            addr += size


