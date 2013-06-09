gdb-heap
========

Forked from https://fedorahosted.org/gdb-heap/

Installation instructions
-------------------------
1. To get this module working with Ubuntu 12.04, make sure you have the following packages installed:

```
sudo apt-get install libc6-dev
sudo apt-get install python-gi
sudo apt-get install libglib2.0-dev
sudo apt-get install python-ply
sudo apt-get install libc6-dbg
```

The original forked version assumes an "import gdb" module, which resides in
"/usr/share/glib-2.0/gdb" and part of the libglib2.0-dev package.

There is also a conflict with the python-gobject-2 library, which are deprecated Python
bindings for the GObject library.  This package installs a glib/ directory inside
/usr/lib/python2.7/dist-packages/glib/option.py, which many Gtk-related modules depend.
You may need to rename this directory before running this system.

2. Create a file that will help automate the loading of the gdbheap library:

gdb-heap-commands:

```
python
import sys
sys.path.append("/usr/share/glib-2.0/gdb")
sys.path.append("/home/rhu/projects/gdb-heap")
sys.path.append("/home/rhu/projects/libheap")
import gdbheap
end
```

To run, you can execute as follows:

sudo gdb -p 7458 -x ~/gdb-heap-commands

