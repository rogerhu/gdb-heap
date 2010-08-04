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

def categorize_sqlite3(addr, usage_set, visited):
    # "struct sqlite3" is defined in src/sqliteInt.h, which is an internal header
    ptr_type = caching_lookup_type('sqlite3').pointer()    
    obj_ptr = gdb.Value(addr).cast(ptr_type)
    # print obj_ptr.dereference()

    aDb = obj_ptr['aDb']
    Db_addr = long(aDb)
    Db_malloc_addr = Db_addr - 8
    if usage_set.set_addr_category(Db_malloc_addr, 'sqlite3 struct Db', visited):
        print aDb['pBt'].dereference()
        # FIXME

