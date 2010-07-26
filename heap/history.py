import datetime
from heap import iter_usage, fmt_size, fmt_addr, sign

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

