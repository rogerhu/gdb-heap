'''
gdb versions vary greatly, this is a central place to
deal with varying capabilities of the underlying gdb and its python bindings
'''
import gdb

# gdb.execute's as_string keyworda argument was added between F13 and F14.
# See https://bugzilla.redhat.com/show_bug.cgi?id=610241

_has_gdb_execute_as_string = True
try:
    # This will either capture the result, or fail before executing,
    # so in neither case should we get noise on stdout:
    gdb.execute('help', as_string=True)
except TypeError:
    _has_gdb_execute_as_string = False

def execute(command):
    '''Equivalent to gdb.execute(as_string=True), returning the output as
    a string rather than logging it to stdout.

    On gdb versions lacking this capability, it uses redirection and temporary
    files to achieve the same result'''
    if _has_gdb_execute_as_string:
        return gdb.execute(command, as_string = True)
    else:
        import tempfile
        f = tempfile.NamedTemporaryFile('r', delete=True)
        gdb.execute("set logging off")
        gdb.execute("set logging redirect off")
        gdb.execute("set logging file %s" % f.name)
        gdb.execute("set logging redirect on")
        gdb.execute("set logging on")
        gdb.execute(command)
        gdb.execute("set logging off")
        gdb.execute("set logging redirect off")
        result = f.read()
        f.close()
        return result

def dump():
    print ('Does gdb.execute have an "as_string" keyword argument? : %s' 
           % _has_gdb_execute_as_string)




