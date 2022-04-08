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

import re
import sys

import gdb

from heap import WrappedPointer, WrappedValue, caching_lookup_type, type_char_ptr, Category

# Use glib's pretty-printers:
dir_ = '/usr/share/glib-2.0/gdb'
if not dir_ in sys.path:
    sys.path.insert(0, dir_)
from glib_gdb import read_global_var, g_quark_to_string


# This was adapted from glib's gobject.py:g_type_to_name
def get_typenode_for_gtype(gtype):
    def lookup_fundamental_type(typenode):
        if typenode == 0:
            return None
        val = read_global_var("static_fundamental_type_nodes")
        if val == None:
            return None

        # glib has an address() call here on the end, which looks wrong
        # (i) it's an attribute, not a method
        # (ii) it converts a TypeNode* to a TypeNode**
        return val[typenode >> 2]

    gtype = int(gtype)
    typenode = gtype - gtype % 4
    if typenode > (255 << 2):
        return gdb.Value(typenode).cast (gdb.lookup_type("TypeNode").pointer())
    else:
        return lookup_fundamental_type (typenode)

def is_typename_castable(typename):
    if typename.startswith('Gtk'):
        return True
    if typename.startswith('Gdk'):
        return True
    if typename.startswith('GType'):
        return True
    if typename.startswith('Pango'):
        return True
    if typename.startswith('GVfs'):
        return True
    return False

class GTypeInstancePtr(WrappedPointer):
    @classmethod
    def from_gtypeinstance_ptr(cls, addr, typenode):
        typename = cls.get_type_name(typenode)
        if typename:
            cls = cls.get_class_for_typename(typename)
            return cls(addr, typenode, typename)

    @classmethod
    def get_class_for_typename(cls, typename):
        '''Get the GTypeInstance subclass for the given type name'''
        if typename in typemap:
            return typemap[typename]
        return GTypeInstancePtr

    def __init__(self, addr, typenode, typename):
        # Try to cast the ptr to the named type:
        addr = gdb.Value(addr)
        try:
            if is_typename_castable(typename):
                # This requires, say, gtk2-debuginfo:
                ptr_type = caching_lookup_type(typename).pointer()
                addr = addr.cast(ptr_type)
                #print typename, addr.dereference()
                #if typename == 'GdkPixbuf':
                #    print 'GOT PIXELS', addr['pixels']
        except RuntimeError as e:
            pass
            #print addr, e

        WrappedPointer.__init__(self, addr)
        self.typenode = typenode
        self.typename = typename
        """
        try:
            print 'self', self
            print 'self.typename', self.typename
            print 'typenode', typenode
            print 'typenode.type', typenode.type
            print 'typenode.dereference()', typenode.dereference()
            print
        except:
            print 'got here'
            raise
        """

    def categorize(self):
        return Category('GType', self.typename, '')

    @classmethod
    def get_type_name(cls, typenode):
        return g_quark_to_string(typenode["qname"])


class GdkColormapPtr(GTypeInstancePtr):
    def categorize_refs(self, usage_set, level=0, detail=None):
        # print 'got here 46'
        pass
        # GdkRgbInfo is stored as qdata on a GdkColormap

class GdkImagePtr(GTypeInstancePtr):
    def categorize_refs(self, usage_set, level=0, detail=None):
        priv_type = caching_lookup_type('GdkImagePrivateX11').pointer()
        priv_data = WrappedPointer(self._gdbval['windowing_data'].cast(priv_type))

        usage_set.set_addr_category(priv_data.as_address(),
                                    Category('GType', 'GdkImagePrivateX11', ''),
                                    level=level+1, debug=True)

        ximage = WrappedPointer(priv_data.field('ximage'))
        dims = '%sw x %sh x %sbpp' % (ximage.field('width'),
                                      ximage.field('height'),
                                      ximage.field('depth'))
        usage_set.set_addr_category(ximage.as_address(),
                                    Category('X11', 'Image', dims),
                                    level=level+2, debug=True)

        usage_set.set_addr_category(int(ximage.field('data')),
                                    Category('X11', 'Image data', dims),
                                    level=level+2, debug=True)

class GdkPixbufPtr(GTypeInstancePtr):
    def categorize_refs(self, usage_set, level=0, detail=None):
        dims = '%sw x %sh' % (self._gdbval['width'],
                              self._gdbval['height'])
        usage_set.set_addr_category(int(self._gdbval['pixels']),
                                    Category('GType', 'GdkPixbuf pixels', dims),
                                    level=level+1, debug=True)

class PangoCairoFcFontMapPtr(GTypeInstancePtr):
    def categorize_refs(self, usage_set, level=0, detail=None):
        # This gives us access to the freetype library:
        FT_Library = WrappedPointer(self._gdbval['library'])

        # This is actually a "struct  FT_LibraryRec_", in FreeType's
        #   include/freetype/internal/ftobjs.h
        # print FT_Library._gdbval.dereference()

        usage_set.set_addr_category(FT_Library.as_address(),
                                    Category('FreeType', 'Library', ''),
                                    level=level+1, debug=True)

        usage_set.set_addr_category(int(FT_Library.field('raster_pool')),
                                    Category('FreeType', 'raster_pool', ''),
                                    level=level+2, debug=True)
        # potentially we could look at FT_Library['memory']


typemap = {
    'GdkColormap':GdkColormapPtr,
    'GdkImage':GdkImagePtr,
    'GdkPixbuf':GdkPixbufPtr,
    'PangoCairoFcFontMap':PangoCairoFcFontMapPtr,
}



def as_gtype_instance(addr, size):
    #type_GObject_ptr = caching_lookup_type('GObject').pointer()
    try:
        type_GTypeInstance_ptr = caching_lookup_type('GTypeInstance').pointer()
    except RuntimeError:
        # Not linked against GLib?
        return None

    gobj = gdb.Value(addr).cast(type_GTypeInstance_ptr)
    try:
        gtype = gobj['g_class']['g_type']
        #print 'gtype', gtype
        typenode = get_typenode_for_gtype(gtype)
        # If I remove the next line, we get errors like:
        #   Cannot access memory at address 0xd1a712caa5b6e5c0
        # Does this line give us an early chance to raise an exception?
        #print 'typenode', typenode
        # It appears to be in the coercion to boolean here:
        # if typenode:
        if typenode is not None:
            #print 'typenode.dereference()', typenode.dereference()
            return GTypeInstancePtr.from_gtypeinstance_ptr(addr, typenode)
    except RuntimeError:
        # Any random buffer that we point this at that isn't a GTypeInstance (or
        # GObject) is likely to raise a RuntimeError at some point in the above
        pass
    return None

# FIXME: currently this ignores G_SLICE
# e.g. use
#    G_SLICE=always-malloc
# to override this
