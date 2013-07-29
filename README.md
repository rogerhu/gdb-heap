gdb-heap
========

Forked from https://fedorahosted.org/gdb-heap/

Installation instructions
-------------------------
1. To get this module working with Ubuntu 12.04, make sure you have the following packages installed:

```
sudo apt-get install libc6-dev
sudo apt-get install libc6-dbg
sudo apt-get install python-gi
sudo apt-get install libglib2.0-dev
sudo apt-get install python-ply
```

The original forked version assumes an "import gdb" module, which resides in
"/usr/share/glib-2.0/gdb" as part of the libglib2.0-dev package.

There is also a conflict with the python-gobject-2 library, which are deprecated
Python bindings for the GObject library.  This package installs a glib/
directory inside /usr/lib/python2.7/dist-packages/glib/option.py, which many
Gtk-related modules depend.  You will therefore need to make sure the sys.path
for /usr/share/glib-2.0/gdb is declared first for this reason (see code
example).

You'll also want to install python-dbg since the package comes with the
debugging symbols for the stock Python 2.7, as well as a python-dbg binary
compiled with the --with-pydebug option that will only work with C extensions
modules compiled with the /usr/include/python2.7_d headers.

2. Create a file that will help automate the loading of the gdbheap library:

gdb-heap-commands:

```
python
import sys
sys.path.insert(0, "/usr/share/glib-2.0/gdb")
sys.path.append("/usr/share/glib-2.0/gdb")
sys.path.append("/home/rhu/projects/gdb-heap")
import gdbheap
end
```

To attach to an existing process, you can execute as follows:

```bash
sudo gdb -p 7458 -x ~/gdb-heap-commands
```

To take a core dump of a process, you can do the following:

```
1) sudo gdb -p <pid>
2) Type "generate-core-file" at the GDB prompt.
3) Wait awhile (and be careful not to hit enter again, since it will repeat the same command)
4) Copy the core.<pid> file somewhere.
```

You can then use gdb to attach to this core file:

```bash
sudo gdb python <core file> -x ~/gdb-heap-commands
```


Commands to run
---------------

```
heap - print a report on memory usage, by category
heap sizes - print a report on memory usage, by sizes
heap used - print used heap chunks
heap free - print free heap chunks
heap all - print all heap chunks
heap log - print a log of recorded heap states
heap label - record the current state of the heap for later comparison
heap diff - compare two states of the heap
heap select - query used heap chunks
hexdump <addr> - print a hexdump, stating at the specific region of memory
heap arenas - print glibs arenas
heap arena <arena> - select glibc arena number
```

Useful resources
----------------

 * http://blip.tv/pycon-us-videos-2009-2010-2011/pycon-2011-dude-where-s-my-ram-a-deep-dive-into-how-python-uses-memory-4896725 (Dude - Where's My RAM?  A deep dive in how Python uses memory - David Malcom's PyCon 2011 video talk)

 * http://dmalcolm.fedorapeople.org/presentations/PyCon-US-2011/GdbPythonPresentation/GdbPython.html (David Malcom's PyCon 2011 slides)

 * http://code.woboq.org/userspace/glibc/malloc/malloc.c.html (malloc.c.html implementation)

 * Malloc per-thread arenas in glibc (http://siddhesh.in/journal/2012/10/24/malloc-per-thread-arenas-in-glibc/)

 * Understanding the heap by breaking it (http://www.blackhat.com/presentations/bh-usa-07/Ferguson/Whitepaper/bh-usa-07-ferguson-WP.pdf)
