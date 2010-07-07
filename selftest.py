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

from test.test_support import run_unittest, findfile

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
            'python sys.path.append(".") ; import heap'
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
        self.assert_('''
Chunk size  Num chunks  Allocated size
----------  ----------  --------------
        32        1500          48,000
    TOTALS        1500          48,000
''' in out)


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
        self.assert_('''
Chunk size  Num chunks  Allocated size
----------  ----------  --------------
   258,048           1         258,048
       272          99          26,928
     1,008           2           2,016
    TOTALS         102         286,992
''' in out)


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
        print out
        # FIXME: do some verification at each breakpoint: check that the reported values correspond to what we expect

    def test_cplusplus(self):
        src = TestSource()
        src.decls += '''
class Foo {
    virtual ~Foo() {}
    int f1;
    int f2;
};
'''
        src.operations += 'Foo *f = new Foo();\n'
        src.add_breakpoint()
        source = src.as_c_source()

        out = self.program_test('test_cplusplus', source, is_cplusplus=True, commands=['run',  'heap sizes'])
        # FIXME: add some verifications
        print out

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
        print out
        # FIXME


    def test_python(self):
        out = self.command_test(['python', '-c', 'id(42)'],
                                commands=['set breakpoint pending yes',
                                          'break builtin_id', 
                                          'run', 
                                          'heap sizes',
                                          'heap'],
                                breakpoint='builtin_id')
        
        # Ensure that the code detected instances of various python types we expect to be present:
        self.assert_('python str' in out)
        self.assert_('python tuple' in out)
        self.assert_('python dict' in out)
        self.assert_('python code' in out)
        self.assert_('python function' in out)
        self.assert_('python list' in out)

        # and of other types:
        self.assert_('string data' in out)
        self.assert_('python pool_header overhead' in out)

        print out

if __name__ == "__main__":
    unittest.main()
