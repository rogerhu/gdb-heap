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

