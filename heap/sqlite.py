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

