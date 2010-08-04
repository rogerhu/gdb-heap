# Utility to help dmalcolm make releases:
VERSION=$1
git clone git://git.fedorahosted.org/gdb-heap.git
git tag -a -m "$VERSION" $VERSION
mv gdb-heap gdb-heap-${VERSION}
tar cfvj gdb-heap-${VERSION}.tar.bz2 gdb-heap-${VERSION}
scp gdb-heap-${VERSION}.tar.bz2 dmalcolm@fedorahosted.org:gdb-heap
