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
gdb versions vary greatly, this is a central place to
deal with varying capabilities of the underlying gdb and its python bindings
'''
import gdb

# gdb.execute's to_string keyword argument was added between F13 and F14.
# See https://bugzilla.redhat.com/show_bug.cgi?id=610241

has_gdb_execute_to_string = True
try:
    # This will either capture the result, or fail before executing,
    # so in neither case should we get noise on stdout:
    gdb.execute('info registers', to_string=True)
except TypeError:
    has_gdb_execute_to_string = False

def execute(command):
    '''Equivalent to gdb.execute(to_string=True), returning the output as
    a string rather than logging it to stdout.

    On gdb versions lacking this capability, it uses redirection and temporary
    files to achieve the same result'''
    if has_gdb_execute_to_string:
        return gdb.execute(command, to_string = True)
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
    print ('Does gdb.execute have an "to_string" keyword argument? : %s' 
           % has_gdb_execute_to_string)




