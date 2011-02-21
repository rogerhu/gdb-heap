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

# Verify that gdb can print information on the heap of an inferior process
#
# Adapted from Python's Lib/test/test_gdb.py, which in turn was adapted from
# similar work in Unladen Swallow's Lib/test/test_jit_gdb.py

import os
import re
from subprocess import Popen, PIPE, call as subprocess_call
import sys
import unittest
import random
from test.test_support import run_unittest, findfile

if sys.maxint == 0x7fffffff:
    _32bit = True
else:
    _32bit = False

try:
    gdb_version, _ = Popen(["gdb", "--version"],
                           stdout=PIPE).communicate()
except OSError:
    # This is what "no gdb" looks like.  There may, however, be other
    # errors that manifest this way too.
    raise unittest.SkipTest("Couldn't find gdb on the path")
gdb_version_number = re.search(r"^GNU gdb [^\d]*(\d+)\.", gdb_version)
if int(gdb_version_number.group(1)) < 7:
    raise unittest.SkipTest("gdb versions before 7.0 didn't support python embedding"
                            " Saw:\n" + gdb_version)

# Verify that "gdb" was built with the embedded python support enabled:
cmd = "--eval-command=python import sys; print sys.version_info"
p = Popen(["gdb", "--batch", cmd], stdout=PIPE)
gdbpy_version, _ = p.communicate()
if gdbpy_version == '':
    raise unittest.SkipTest("gdb not built with embedded python support")

class TestSource(object):
    '''Programatically construct C source code for a test program that calls into the heap'''
    def __init__(self):
        self.decls = ''
        self.operations = ''
        self.num_ptrs = 0
        self.indent = '    '

    def add_line(self, code):
        self.operations += self.indent + code + '\n'

    def add_malloc(self, size, debug=False, typename=None):
        self.num_ptrs += 1
        varname = 'ptr%03i'% self.num_ptrs

        if typename:
            cast = '(%s)' % typename
        else:
            typename = 'void *'
            cast = ''

        self.add_line('%s%s = %smalloc(0x%x); /* %i */'
                      % (typename, varname, cast, size, size))
        if debug:
            self.add_line('printf(__FILE__ ":%%i:%s=%%p\\n", __LINE__, %s);'
                          % (varname, varname))
            self.add_line('fflush(stdout);')
        return varname

    def add_realloc(self, varname, size, debug=False):
        self.num_ptrs += 1
        new_varname = 'ptr%03i'% self.num_ptrs
        self.add_line('void *%s = realloc(%s, 0x%x);'
                      % (new_varname, varname, size))
        if debug:
            self.add_line('printf(__FILE__ ":%%i:%s=%%p\\n", __LINE__, %s);'
                          % (new_varname, new_varname))
            self.add_line('fflush(stdout);')
        return new_varname

    def add_free(self, varname, debug=False):
        self.add_line('free(%s);' % varname)

    def add_breakpoint(self):
        self.add_line('__asm__ __volatile__ ("int $03");')

    def as_c_source(self):
        result = '''
#include <stdio.h>
#include <stdlib.h>
'''
        result += self.decls
        result += '''
int
main (int argc, char **argv)
{
''' + self.operations + '''
    return 0;
}
'''
        return result
        

class TestProgram(object):
    def __init__(self, name, source, is_cplusplus=False):
        self.name = name
        self.source = source

        if is_cplusplus:
            self.srcname = '%s.cc' % self.name
            compiler = 'g++'
        else:
            self.srcname = '%s.c' % self.name
            compiler = 'gcc'

        f = open(self.srcname, 'w')
        f.write(source)
        f.close()
        
        c = subprocess_call([compiler,

                             # We want debug information:
                             '-g', 
                             
                             # Name of the binary:
                             '-o', self.name,

                             # The source file:
                             self.srcname]) 
        # Check exit status:
        assert(c == 0)
        
        # Check that the binary exists:
        assert(os.path.exists(self.name))

from resultparser import ParsedTable, RowNotFound, test_table

class DebuggerTests(unittest.TestCase):

    """Test that the debugger can debug the heap"""

    def run_gdb(self, *args):
        """Runs gdb with the command line given by *args.

        Returns its stdout, stderr
        """
        out, err = Popen(args, stdout=PIPE, stderr=PIPE).communicate()
        return out, err


    def requires_binary(self, binary):
        # Slightly complicated: gdb will look for the binary within the PWD
        # as well as within the $PATH

        if os.path.exists(binary):
            # It's either an absolute or relative path, and directly exists:
            return

        p = Popen(['which', binary], stdout=PIPE, stderr=PIPE)
        out, err = p.communicate()
        if p.returncode == 0:
            # It's in the $PATH
            return

        raise unittest.SkipTest("%s not found" % binary)

    def command_test(self, progargs, commands, breakpoint=None):

        self.requires_binary(progargs[0])

        # Run under gdb, hit the breakpoint, then run our "heap" command:
        commands =  [
            'python sys.path.append(".") ; import gdbheap'
            ] + commands
        args = ["gdb", "--batch"]
        args += ['--eval-command=%s' % cmd for cmd in commands]
        args += ["--args"] + progargs

        # print args
        # print ' '.join(args)

        # Use "args" to invoke gdb, capturing stdout, stderr:
        out, err = self.run_gdb(*args)

        # Ignore some noise on stderr due to a pending breakpoint:
        if breakpoint:
            err = err.replace('Function "%s" not defined.\n' % breakpoint, '')

        # Ensure no unexpected error messages:
        if err != '':
            print out
            print err
            self.fail('stderr from gdb was non-empty: %r' % err)

        return out        

    def program_test(self, name, source, commands, is_cplusplus=False):
        p = TestProgram(name, source, is_cplusplus)
        return self.command_test([p.name], commands)

    def test_no_allocations(self):
        # Verify handling of an inferior process that doesn't use the heap
        src = TestSource()
        src.add_breakpoint()
        source = src.as_c_source()

        out = self.program_test('test_no_allocations', source, commands=['run',  'heap sizes'])
        self.assert_('''
Chunk size  Num chunks  Allocated size
----------  ----------  --------------
    TOTALS           0               0
''' in out)

    def test_small_allocations(self):
        src = TestSource()
        # 100 allocations each of sizes in the range 1-15
        for i in range(100):
            for size in range(1, 16):
                src.add_malloc(size)
        src.add_breakpoint()
        source = src.as_c_source()

        out = self.program_test('test_small_allocations', source, commands=['run',  'heap sizes'])

        if _32bit:
            exp = '''
Chunk size  Num chunks  Allocated size
----------  ----------  --------------
        16        1200          19,200
        24         300           7,200
    TOTALS        1500          26,400
'''
        else:
            exp = '''
Chunk size  Num chunks  Allocated size
----------  ----------  --------------
        32        1500          48,000
    TOTALS        1500          48,000
'''
        self.assert_(exp in out, out)


    def test_large_allocations(self):
        # 10 allocations each of sizes in the range 1MB through 10MB:
        src = TestSource()
        for i in range(10):
            size = 1024 * 1024 * (i+1)
            src.add_malloc(size)
        src.add_breakpoint()
        source = src.as_c_source()

        out = self.program_test('test_large_allocations', source, commands=['run',  'heap sizes'])
        self.assert_('''
Chunk size  Num chunks  Allocated size
----------  ----------  --------------
10,489,856           1      10,489,856
 9,441,280           1       9,441,280
 8,392,704           1       8,392,704
 7,344,128           1       7,344,128
 6,295,552           1       6,295,552
 5,246,976           1       5,246,976
 4,198,400           1       4,198,400
 3,149,824           1       3,149,824
 2,101,248           1       2,101,248
 1,052,672           1       1,052,672
    TOTALS          10      57,712,640
''' in out)

    def test_mixed_allocations(self):
        # Compile test program
        source = '''
#include <stdio.h>
#include <stdlib.h>

int
main (int argc, char **argv)
{
    int i;
    void *ptrs[100];
    /* Some small allocations: */
    for (i=0; i < 100; i++) {
        ptrs[i] = malloc(256);
        printf("malloc returned %p\\n", ptrs[i]);
        fflush(stdout);
    }

    /* Free one of the small allocations: */
    free(ptrs[50]);

    void* ptr1 = malloc(1000);
    void* ptr2 = malloc(1000);
    void* ptr3 = malloc(256000); /* large allocation */

    /* Directly insert a breakpoint: */
    __asm__ __volatile__ ("int $03");

    return 0;
}
'''

        out = self.program_test('test_simple', source, commands=['run',  'heap sizes'])
        #print out

        # Verify the result
        if _32bit:
            exp = '''
Chunk size  Num chunks  Allocated size
----------  ----------  --------------
   258,048           1         258,048
       264          99          26,136
     1,008           2           2,016
    TOTALS         102         286,200
'''
        else:
            exp = '''
Chunk size  Num chunks  Allocated size
----------  ----------  --------------
   258,048           1         258,048
       272          99          26,928
     1,008           2           2,016
    TOTALS         102         286,992
'''
        self.assert_(exp in out, out)


    def random_size(self):
        size = random.randint(1, 64)
        if random.randint(0, 5) == 0:
            size *= 1024
            size += random.randint(0, 1023)
        if random.randint(0, 5) == 0:
            size *= 256
            size += random.randint(0, 255)
        return size

    def test_random_allocations(self):
        # Fuzz-testing: lots of allocations (of various sizes)
        # and deallocations
        src = TestSource()
        sizes = {}
        live_blocks = set()
        for i in range(100):
            action = random.randint(1, 100)

            # 70% chance of malloc:
            if action <= 70:
                size = self.random_size()
                varname = src.add_malloc(size, debug=True)
                sizes[varname] = size
                live_blocks.add(varname)
            if len(live_blocks) > 0:
                # 10% chance of realloc:
                if action in range(71, 80):
                    size = self.random_size()
                    old_varname = random.sample(live_blocks, 1)[0]
                    live_blocks.remove(old_varname)
                    new_varname = src.add_realloc(old_varname, size, debug=True)
                    sizes[new_varname] = size
                    live_blocks.add(new_varname)
                # 20% chance of freeing something:
                elif action > 80:
                    varname = random.sample(live_blocks, 1)[0]
                    live_blocks.remove(varname)
                    src.add_free(varname)
            src.add_breakpoint()

        source = src.as_c_source()

        out = self.program_test('test_random_allocations', source,
                                commands=(['run']
                                          + ['heap select', 'cont'] * 100))

        # We have 100 states of the inferior process; check that each was
        # reported as we expected it to be:
        tables = ParsedTable.parse_lines(out)
        self.assertEqual(len(tables), 100)
        for i in range(100):
            heap_select_out = tables[i]
            #print heap_select_out
            reported_addrs = set([heap_select_out.get_cell(0, y)
                                  for y in range(len(heap_select_out.rows))])
            #print reported_addrs

        # FIXME: do some verification at each breakpoint: check that the
        # reported values correspond to what we expect

    def test_random_buffers(self):
        # Fuzz-testing: try to break the heuristics by throwing random bytes
        # at them.  Note that we do the randomization at the python level when
        # generating the C code, so that the result of running any given C code
        # is entirely reproducable
        src = TestSource()
        for i in range(100):
            varname = src.add_malloc(256, typename='unsigned char*')
            for offset in range(256):
                value = random.randint(0, 255)
                src.add_line('%s[%i]=0x%02x;' % (varname, offset, value))
        src.add_breakpoint()
        source = src.as_c_source()
        out = self.program_test('test_random_buffers', source, commands=['run',  'heap'])
        # print out


    def test_cplusplus(self):
        '''Verify that we can detect and categorize instances of C++ classes'''
        # Note that C++ detection is currently disabled due to a bug in execution capture
        src = TestSource()
        src.decls += '''
class Foo {
public:
    virtual ~Foo() {}
    int f1;
    int f2;
};
class Bar : Foo {
public:
    virtual ~Bar() {}
    int f1;
    // Ensure that Bar has a different allocated size to Foo, on every arch:
    int buffer[256];
};
'''
        for i in range(100):
            src.add_line('{Foo *f = new Foo();}')
            if i % 2:
                src.add_line('{Bar *b = new Bar();}')
        src.add_breakpoint()
        source = src.as_c_source()

        out = self.program_test('test_cplusplus', source, is_cplusplus=True, commands=['run',  'heap sizes', 'heap'])
        tables = ParsedTable.parse_lines(out)
        heap_sizes_out = tables[0]
        heap_out = tables[1]

        # We ought to have 150 live blocks on the heap:
        self.assertHasRow(heap_out,
                          [('Detail', 'TOTAL'), ('Count', 150)])

        # Use the differing counts of the blocks to locate the objects
        # FIXME: change the "Domain" values below and add "Kind" once C++
        # identification is re-enabled:
        self.assertHasRow(heap_out,
                          [('Count', 100), ('Domain', 'uncategorized')])
        self.assertHasRow(heap_out,
                          [('Count', 50),  ('Domain', 'uncategorized')])

    def test_history(self):
        src = TestSource()
        src.add_malloc(100)
        src.add_malloc(100)
        src.add_malloc(100)
        src.add_breakpoint()


        src.add_malloc(200)
        src.add_malloc(200)
        src.add_malloc(200)
        src.add_breakpoint()
        source = src.as_c_source()

        out = self.program_test('test_history', source, 
                                commands=['run', 'heap sizes', 'heap label foo', 'cont', 'heap log', 'heap diff'])
        #print out
        # FIXME


    def assertHasRow(self, table, kvs):
        return table.find_row(kvs)
        # ...which will raise a RowNotFound exception if there's a problem

    def assertFoundCategory(self, table, domain, kind, detail=None):
        # Ensure that the result table has a row of the given category
        # (or raise RowNotFound)
        kvs = [('Domain', domain),
               ('Kind', kind)]
        if detail:
            kvs.append( ('Detail', detail) )

        self.assertHasRow(table, kvs)

    def test_assertions(self):
        # Ensure that the domain-specific assertions work
        tables = ParsedTable.parse_lines(test_table)
        self.assertEquals(len(tables), 2)
        pt = tables[0]

        self.assertHasRow(pt, [('Domain', 'python'), ('Kind', 'str')])
        self.assertRaises(RowNotFound,
                          lambda: self.assertHasRow(pt, [('Domain', 'ruby')]))

        self.assertFoundCategory(pt, 'python', 'str')
        self.assertRaises(RowNotFound,
                          lambda: self.assertFoundCategory(pt, 'ruby', 'class'))

    def test_gobject(self):
        out = self.command_test(['gtk-demo'],
                                commands=['set breakpoint pending yes',
                                          'set environment G_SLICE=always-malloc', # for now
                                          'break gtk_main',
                                          'run',
                                          'heap',
                                          ])
        # print out

        tables = ParsedTable.parse_lines(out)
        heap_out = tables[0]

        # Ensure that instances of GObject classes are categorized:
        self.assertFoundCategory(heap_out, 'GType', 'GtkTreeView')
        self.assertFoundCategory(heap_out, 'GType', 'GtkLabel')

        # Ensure that instances of fundamental boxed types are categorized:
        self.assertFoundCategory(heap_out, 'GType', 'gchar')
        self.assertFoundCategory(heap_out, 'GType', 'guint')

        # Ensure that the code detected buffers used by the GLib/GTK types:
        self.assertFoundCategory(heap_out,
                                 'GType', 'GdkPixbuf pixels', '107w x 140h')

        # GdkImage -> X11 Images -> data:
        self.assertFoundCategory(heap_out, 'GType', 'GdkImage')
        self.assertFoundCategory(heap_out, 'X11', 'Image')
        if False:
            # Only seen whilst using X forwarded over ssh:
            self.assertFoundCategory(heap_out, 'X11', 'Image data')
        # In both above rows, "Detail" contains the exact dimensions, but these
        # seem to vary with the resolution of the display the test is run
        # against

        # FreeType:
        # These seem to be highly dependent on the environment; I originally
        # developed this whilst using X forwarded over ssh
        if False:
            self.assertFoundCategory(heap_out, 'GType', 'PangoCairoFcFontMap')
            self.assertFoundCategory(heap_out, 'FreeType', 'Library')
            self.assertFoundCategory(heap_out, 'FreeType', 'raster_pool')

    def test_python2(self):
        self._impl_test_python('python2', py3k=False)

    def test_python3(self):
        self._impl_test_python('python3', py3k=True)

    def _impl_test_python(self, pyruntime, py3k):
        # Test that we can debug CPython's memory usage, for a given runtime

        # Invoke a test python script, stopping at a breakpoint
        out = self.command_test([pyruntime, 'object-sizes.py'],
                                commands=['set breakpoint pending yes',
                                          'break builtin_id',
                                          'run',
                                          'heap',
                                          'heap select kind="PyListObject ob_item table"'],
                                breakpoint='builtin_id')

        # Re-enable this for debugging:
        # print out

        tables = ParsedTable.parse_lines(out)
        heap_out = tables[0]

        # Verify that "select" works for a category that's only detectable
        # w.r.t. other categories:
        select_out = tables[1]
        # print select_out
        self.assertHasRow(select_out,
                          kvs = [('Domain', 'cpython'),
                                 ('Kind', 'PyListObject ob_item table')])
        
        # Ensure that the code detected instances of various python types we
        # expect to be present:
        for kind in ('str', 'list', 'tuple', 'dict', 'type', 'code',
                     'set', 'frozenset', 'function', 'module', 'frame', ):
            self.assertFoundCategory(heap_out, 'python', kind)

        if py3k:
            self.assertFoundCategory(heap_out, 'python', 'bytes')
        else:
            self.assertFoundCategory(heap_out, 'python', 'unicode')

        # Ensure that the blocks of int allocations are detected:
        if not py3k:
            self.assertFoundCategory(heap_out, 'cpython', '_intblock', '')

        # Ensure that bytecode "strings" are marked as such:
        self.assertFoundCategory(heap_out, 'python', 'str', 'bytecode') # FIXME

        # Ensure that old-style classes are printed with a meaningful name
        # (i.e. not just "type"):
        if not py3k:
            for clsname in ('OldStyle', 'OldStyleManyAttribs'):
                self.assertFoundCategory(heap_out,
                                         'python', clsname, 'old-style')

                # ...and that their instance dicts are marked:
                self.assertFoundCategory(heap_out,
                                         'cpython', 'PyDictObject',
                                         '%s.__dict__' % clsname)

        # ...and that an old-style instance with enough attributes to require a
        # separate PyDictEntry buffer for its __dict__ has that buffer marked
        # with the typename:
        self.assertFoundCategory(heap_out,
                                 'cpython', 'PyDictEntry table',
                                 'OldStyleManyAttribs.__dict__')

        # Likewise for new-style classes:
        for clsname in ('NewStyle', 'NewStyleManyAttribs'):
            self.assertHasRow(heap_out,
                              [('Domain', 'python'),
                               ('Kind',   clsname),
                               ('Detail', None)])
            self.assertFoundCategory(heap_out,
                              'python', 'dict', '%s.__dict__' % clsname)
        self.assertFoundCategory(heap_out,
                                 'cpython', 'PyDictEntry table',
                                 'NewStyleManyAttribs.__dict__')

        # Ensure that the code detected buffers used by python types:
        for kind in ('PyDictEntry table', 'PyListObject ob_item table',
                     'PySetObject setentry table',
                     'PyUnicodeObject buffer', 'PyDictEntry table'):
            self.assertFoundCategory(heap_out,
                                     'cpython', kind)

        # and of other types:
        self.assertFoundCategory(heap_out,
                                 'C', 'string data')
        self.assertFoundCategory(heap_out,
                                 'pyarena', 'pool_header overhead')

        # Ensure that the "interned" table is identified (it's typically
        # at least 200k on a 64-bit build):
        self.assertHasRow(heap_out,
                          [('Domain', 'cpython'),
                           ('Kind',   'PyDictEntry table'),
                           ('Detail', 'interned'),
                           ('Count',  1)])


        # Ensure that we detect python sqlite3 objects:
        for kind in ('sqlite3.Connection', 'sqlite3.Statement',
                     'sqlite3.Cache'):
            self.assertFoundCategory(heap_out,
                                     'python', kind)
        # ...and that we detect underlying sqlite3 buffers:
        for kind in ('sqlite3', 'sqlite3_stmt'):
            self.assertFoundCategory(heap_out,
                                     'sqlite3', kind)

    def test_pypy(self):
        # Try to investigate memory usage of pypy-c
        # Developed using pypy-1.4.1 as packaged on Fedora.
        #
        # In order to get meaningful data, let's try to trap the exit point
        # of pypy-c within gdb.
        #
        # For now, lets try to put a breakpoint in this location within the
        # generated "pypy_g_entry_point" C function:
        #   print_stats:158 :         debug_stop("jit-summary")
        out = self.command_test(['pypy', 'object-sizes.py'],
                                commands=['set breakpoint pending yes',

                                          'break pypy_debug_stop',
                                          'condition 1 0==strcmp(category, "jit-summary")',

                                          'run',
                                          'heap',
                                          ])
        tables = ParsedTable.parse_lines(out)
        select_out = tables[0]

    def test_select(self):
        # Ensure that "heap select" with no query does something sane
        src = TestSource()
        for i in range(3):
            src.add_malloc(1024)
        src.add_breakpoint()
        source = src.as_c_source()

        out = self.program_test('test_select', source,
                                commands=['run',
                                          'heap select',
                                          ])
        tables = ParsedTable.parse_lines(out)
        select_out = tables[0]

        # The "heap select" command should select all blocks:
        self.assertEquals(select_out.colnames,
                          ('Start', 'End', 'Domain', 'Kind', 'Detail', 'Hexdump'))
        self.assertEquals(len(select_out.rows), 3)


        # Test that syntax errors are well handled:
        out = self.program_test('test_select', source,
                                commands=['run',
                                          'heap select I AM A SYNTAX ERROR',
                                          ])
        errmsg = '''
Parse error at "AM":
I AM A SYNTAX ERROR
  ^^
'''
        if errmsg not in out:
            self.fail('Did not find expected "ParseError" message in:\n%s' % out)

        # Test that unknown attributes are well-handled:
        out = self.program_test('test_select', source,
                                commands=['run',
                                          'heap select NOT_AN_ATTRIBUTE > 42',
                                          ])
        errmsg = '''
Unknown attribute "NOT_AN_ATTRIBUTE" (supported are domain,kind,detail,addr,start,size) at "NOT_AN_ATTRIBUTE":
NOT_AN_ATTRIBUTE > 42
  ^^^^^^^^^^^^^^^^
'''
        if errmsg not in out:
            self.fail('Did not find expected "Unknown attribute" error message in:\n%s' % out)

        # Ensure that ply did not create debug files (ticket #12)
        for filename in ('parser.out', 'parsetab.py'):
            if os.path.exists(filename):
                self.fail('Unexpectedly found file %r' % filename)

    def test_select_by_size(self):
        src = TestSource()
        # Allocate ten 1kb blocks, nine 2kb blocks, etc, down to one 10kb
        # block so that we can easily query them by size:
        for i in range(10):
            for j in range(10-i):
                size = 1024 * (i+1)
                src.add_malloc(size)
        src.add_breakpoint()
        source = src.as_c_source()

        out = self.program_test('test_select_by_size', source,
                                commands=['run',
                                          'heap',

                                          'heap select size >= 10240',
                                          # (parsed as "largest_out" below)

                                          'heap select size < 2048',
                                          # (parsed as "smallest_out" below)

                                          'heap select size >= 4096 and size < 8192',
                                          # (parsed as "middle_out" below)
                                          ])
        tables = ParsedTable.parse_lines(out)
        heap_out = tables[0]
        largest_out = tables[1]
        smallest_out = tables[2]
        middle_out = tables[3]

        # The "heap" command should find all the allocations:
        self.assertHasRow(heap_out,
                          [('Detail', 'TOTAL'), ('Count', 55)])

        # The query for the largest should find just one allocation:
        self.assertEquals(len(largest_out.rows), 1)

        # The query for the smallest should find ten allocations:
        self.assertEquals(len(smallest_out.rows), 10)

        # The middle query [4096, 8192) should capture the following
        # allocations:
        #   7 of (4*4096), 6 of (5*4096), 5 of (6*4096) and 4 of (7*4096)
        # giving a total count of 7+6+5+4 = 22
        self.assertEquals(len(middle_out.rows), 22)

    def test_select_by_category(self):
        out = self.command_test(['python', '-c', 'id(42)'],
                                commands=['set breakpoint pending yes',
                                          'break builtin_id',
                                          'run',
                                          'heap select domain="python" and kind="str" and size > 512'],
                                breakpoint='builtin_id')

        tables = ParsedTable.parse_lines(out)
        select_out = tables[0]

        # Ensure that the filtering mechanism worked:
        if len(select_out.rows) < 10:
            self.fail("Didn't find any large python strings (has something gone wrong?) in: %s" % select_out)
        for row in select_out.rows:
            self.assertEquals(row[2], 'python')
            self.assertEquals(row[3], 'str')

    def test_heap_used(self):
        # Ensure that "heap used" works
        src = TestSource()
        for i in range(3):
            src.add_malloc(1024)
        src.add_breakpoint()
        source = src.as_c_source()

        out = self.program_test('test_heap_used', source,
                                commands=['run',
                                          'heap used',
                                          ])
        # FIXME: do some verification of the output

    def test_heap_all(self):
        # Ensure that "heap all" works
        src = TestSource()
        for i in range(3):
            src.add_malloc(1024)
        src.add_breakpoint()
        source = src.as_c_source()

        out = self.program_test('test_heap_all', source,
                                commands=['run',
                                          'heap all',
                                          ])
        # FIXME: do some verification of the output


from heap.parser import parse_query
from heap.query import Constant, And, Or, Not, GetAttr, \
    Comparison__le__, Comparison__lt__, Comparison__eq__, \
    Comparison__ne__, Comparison__ge__, Comparison__gt__

class QueryParsingTests(unittest.TestCase):
    def assertParsesTo(self, s, result):
        self.assertEquals(parse_query(s), result)

    def test_simple_comparisons(self):
        self.assertParsesTo('size >= 1024',
                            Comparison__ge__(GetAttr('size'), Constant(1024)))

        # Check that hexadecimal numeric literals are parsed:
        self.assertParsesTo('addr > 0xbf70ffff',
                            Comparison__gt__(GetAttr('addr'), Constant(0xbf70ffff)))

        # Check that string literals are parsed:
        self.assertParsesTo('kind == "str"',
                            Comparison__eq__(GetAttr('kind'), Constant('str')))

        # Check "and":
        self.assertParsesTo('kind == "str" and size > 1024',
                            And(Comparison__eq__(GetAttr('kind'), Constant('str')),
                                Comparison__gt__(GetAttr('size'), Constant(1024))))

        # Check "or":
        self.assertParsesTo('size > 10000 and not domain="uncategorized"',
                            And(Comparison__gt__(GetAttr('size'), Constant(10000)),
                                Not(Comparison__eq__(GetAttr('domain'), Constant('uncategorized')))))

        # Do we want algebraic support?
        #self.assertParsesTo('size == (256 * 1024)+8',
        #                    Comparison('size', '==', 1024L))


if __name__ == "__main__":
    unittest.main()
