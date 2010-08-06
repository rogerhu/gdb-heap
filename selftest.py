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
import subprocess
import sys
import unittest
import random
from collections import namedtuple
from test.test_support import run_unittest, findfile

if sys.maxint == 0x7fffffff:
    _32bit = True
else:
    _32bit = False

try:
    gdb_version, _ = subprocess.Popen(["gdb", "--version"],
                                      stdout=subprocess.PIPE).communicate()
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
p = subprocess.Popen(["gdb", "--batch", cmd],
                     stdout=subprocess.PIPE)
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

    def add_malloc(self, size, debug=False):
        self.num_ptrs += 1
        varname = 'ptr%03i'% self.num_ptrs
        self.operations += self.indent + 'void *%s = malloc(0x%x); /* %i */\n' % (varname, size, size)
        if debug:
            self.operations += self.indent + 'printf(__FILE__ ":%%i:%s=%%p\\n", __LINE__, %s);\n' % (varname, varname)
            self.operations += self.indent + 'fflush(stdout);\n'
        return varname

    def add_realloc(self, varname, size, debug=False):
        self.num_ptrs += 1
        new_varname = 'ptr%03i'% self.num_ptrs
        self.operations += self.indent + 'void *%s = realloc(%s, 0x%x);\n' % (new_varname, varname, size)
        if debug:
            self.operations += self.indent + 'printf(__FILE__ ":%%i:%s=%%p\\n", __LINE__, %s);\n' % (new_varname, new_varname)
            self.operations += self.indent + 'fflush(stdout);\n'
        return new_varname

    def add_free(self, varname, debug=False):
        self.operations += self.indent + 'free(%s);\n' % varname

    def add_breakpoint(self):
        self.operations += self.indent + '__asm__ __volatile__ ("int $03");\n'

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
        
        c = subprocess.call([compiler,

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

class ColumnNotFound(Exception):
    def __init__(self, colname):
        self.colname = colname

def indent(str_):
    return '\n'.join([(' ' * 4) + line
                      for line in str_.splitlines()])

class RowNotFound(Exception):
    def __init__(self, criteria, table):
        self.criteria = criteria
        self.table = table
    def __str__(self):
        return 'RowNotFound(%s) in:\n%s' % (self.criteria, indent(str(self.table)))

class Criteria(object):
    '''A list of (colname, value) criteria for searching rows in a table'''
    def __init__(self, table, kvs):
        self.kvs = kvs
        self._by_index = [(table.find_col(attrname), value)
                          for attrname, value in kvs]

    def __str__(self):
        return 'Criteria(%s)' % ','.join('%r=%r' % (attrname, value)
                                         for attrname, value in self.kvs)

    def is_matched_by(self, row):
        for colindex, value in self._by_index:
            if row[colindex] != value:
                return False
        return True

class ParsedTable(object):
    '''Parses output from heap.Table, for use in writing selftests'''
    @classmethod
    def parse_lines(cls, data):
        '''Parse the lines in the string, returning a list of ParsedTable
        instances'''
        result = []
        lines = data.splitlines()
        start = 0
        while start < len(lines):
            sep_line = cls._find_separator_line(lines[start:])
            if sep_line:
                sep_index, colmetrics = sep_line
                t = ParsedTable(sep_index, colmetrics, lines[start:])
                result.append(t)
                start += t.sep_index + 1 + len(t.rows)
            else:
                break
        return result

    # Column metrics:
    ColMetric = namedtuple('ColMetric', ('offset', 'width'))
        
    def __init__(self, sep_index, colmetrics, lines):
        self.sep_index, self.colmetrics = sep_index, colmetrics

        # Parse column headings:
        header_index = self.sep_index - 1
        self.colnames = self._split_cells(lines[header_index])

        # Parse rows:
        self.rows = []
        for line in lines[self.sep_index + 1:]:
            if line == '':
                break
            self.rows.append(self._split_cells(line))

        self.rawdata = '\n'.join(lines[header_index:header_index+len(self.rows)+2])

    def __str__(self):
        return self.rawdata
            
    def get_cell(self, x, y):
        return self.rows[y][x]

    def find_col(self, colname):
        # Find the index of the column with the given name
        for x, col in enumerate(self.colnames):
            if colname == col:
                return x
        raise ColumnNotFound(colname)

    def find_row(self, kvs):
        # Find the first row matching the criteria, or raise RowNotFound
        criteria = Criteria(self, kvs)
        for row in self.rows:
            if criteria.is_matched_by(row):
                return row
        raise RowNotFound(criteria, self)

    def find_cell(self, kvs, attr2name):
        criteria = Criteria(self, kvs)
        row = self.find_row(kvs)
        return row[self.find_col(attr2name)]

    def _split_cells(self, line):
        row = []
        for col in self.colmetrics:
            cell = line[col.offset: col.offset+col.width].lstrip()
            if cell == '':
                cell = None
            else:
                # Remove ',' separators from numbers:
                m = re.match('^([0-9,]+)$', cell) # [0-9]\,
                if m:
                    cell = int(cell.replace(',', ''))
                    
            row.append(cell)
        return tuple(row)

    @classmethod
    def _find_separator_line(cls, lines):
        # Look for the separator line
        # Return (index, tuple of ColMetric)
        for i, line in enumerate(lines):
            if line.startswith('-'):
                widths = [len(frag) for frag in line.split('  ')]
                coldata = []
                offset = 0
                for width in widths:
                    coldata.append(cls.ColMetric(offset=offset, width=width))
                    offset += width + 2
                return (i, tuple(coldata))
            

# Test data for table parsing (edited fragment of output during development):
test_table = '''
junk line

       Domain        Kind                 Detail  Count  Allocated size
-------------  ----------  ---------------------  -----  --------------
       python         str                         3,891         234,936
uncategorized                        98312 bytes      1          98,312
uncategorized                         1544 bytes     43          66,392
uncategorized                         6152 bytes     10          61,520
       python       tuple                         1,421          54,168
                                           TOTAL  9,377         857,592

another junk line

another table

Chunk size  Num chunks  Allocated size
----------  ----------  --------------
        16         100           1,600
        24          50           1,200
    TOTALS         150           2,800

more junk
'''

class ParserTests(unittest.TestCase):
    def test_table_data(self):
        tables = ParsedTable.parse_lines(test_table)
        self.assertEquals(len(tables), 2)
        pt = tables[0]

        # Verify column names:
        self.assertEquals(pt.colnames, ('Domain', 'Kind', 'Detail', 'Count', 'Allocated size'))

        # Verify (x,y) lookup, and type conversions:
        self.assertEquals(pt.get_cell(0, 0), 'python')
        self.assertEquals(pt.get_cell(1, 3), None)
        self.assertEquals(pt.get_cell(4, 5), 857592)

        # Verify searching by value:
        self.assertEquals(pt.find_col('Count'), 3)
        self.assertEquals(pt.find_row([('Allocated size', 54168),]),
                          ('python', 'tuple', None, 1421, 54168))
        self.assertEquals(pt.find_cell([('Kind', 'str'),], 'Count'), 3891)

        # Error-checking:
        self.assertRaises(ColumnNotFound,
                          pt.find_col, 'Ensure that a non-existant column raises an error')
        self.assertRaises(RowNotFound,
                          pt.find_row, [('Count', -1)])

        # Verify that "rawdata" contains the correct string data:
        self.assert_(pt.rawdata.startswith('       Domain'))
        self.assert_(pt.rawdata.endswith('857,592'))

        # Test the second table:
        pt = tables[1]
        self.assertEquals(pt.colnames, ('Chunk size', 'Num chunks', 'Allocated size'))
        self.assertEquals(pt.get_cell(2, 2), 2800)
        self.assert_(pt.rawdata.startswith('Chunk size'))
        self.assert_(pt.rawdata.endswith('2,800'))


    def test_multiple_tables(self):
        tables = ParsedTable.parse_lines(test_table * 5)
        self.assertEquals(len(tables), 10)

class DebuggerTests(unittest.TestCase):

    """Test that the debugger can debug the heap"""

    def run_gdb(self, *args):
        """Runs gdb with the command line given by *args.

        Returns its stdout, stderr
        """
        out, err = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            ).communicate()
        return out, err


    def command_test(self, progargs, commands, breakpoint=None):
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

        out = self.program_test('test_random_allocations', source, commands=['run'] + ['heap sizes', 'cont'] * 100)
        #print out
        # FIXME: do some verification at each breakpoint: check that the reported values correspond to what we expect

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
            src.operations += '{Foo *f = new Foo();}\n'
            if i % 2:
                src.operations += '{Bar *b = new Bar();}\n'
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
        # indentification is re-enabled:
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

    def test_python(self):
        out = self.command_test(['python', '-c', 'id(42)'],
                                commands=['set breakpoint pending yes',
                                          'break builtin_id', 
                                          'run', 
                                          'heap sizes',
                                          'heap'],
                                breakpoint='builtin_id')

        # Re-enable this for debugging:
        # print out

        tables = ParsedTable.parse_lines(out)
        heap_sizes_out = tables[0]
        heap_out = tables[1]
        
        # Ensure that the code detected instances of various python types we expect to be present:
        for kind in ('str', 'tuple', 'dict', 'code', 'function', 'list'):
            self.assertHasRow(heap_out, 
                              [('Kind', kind), ('Domain', 'python')])

        # and of other types:
        self.assertHasRow(heap_out,
                          [('Kind', 'string data'),
                           ('Domain', 'C')])
        self.assertHasRow(heap_out,
                          [('Kind', 'pool_header overhead'),
                           ('Domain', 'pyarena')])


from heap.parser import parse_query, Comparison, And
class QueryParsingTests(unittest.TestCase):
    def assertParsesTo(self, s, result):
        self.assertEquals(parse_query(s), result)

    def test_simple_comparisons(self):
        self.assertParsesTo('size >= 1024',
                            Comparison('size', '>=', 1024L))
        self.assertParsesTo('addr > 0xbf70ffff',
                            Comparison('addr', '>', 0xbf70ffff))

        self.assertParsesTo('kind == "str"',
                            Comparison('kind', '==', 'str'))

        self.assertParsesTo('kind == "str" and size > 1024',
                            And(Comparison('kind', '==', 'str'),
                                Comparison('size', '>', 1024L)))

        # Do we want algebraic support?
        #self.assertParsesTo('size == (256 * 1024)+8',
        #                    Comparison('size', '==', 1024L))


if __name__ == "__main__":
    unittest.main()
