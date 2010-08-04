# Utility to help dmalcolm make releases:
VERSION=$1
git clone git://git.fedorahosted.org/gdb-heap.git

pushd gdb-heap
git tag -a -m "$VERSION" $VERSION
# FIXME: pushing this isn't working for some reason
popd

mv gdb-heap gdb-heap-${VERSION}
tar cfvj gdb-heap-${VERSION}.tar.bz2 gdb-heap-${VERSION}
scp gdb-heap-${VERSION}.tar.bz2 dmalcolm@fedorahosted.org:gdb-heap
rm -rf gdb-heap-${VERSION}
