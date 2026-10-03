Linux-only packages for the Vercel deployment (loaded by api/index.py, ignored elsewhere):
- moss 1.14.0 and inferedge-moss-core 0.26.0 (manylinux_2_35 wheel; binary needs only GLIBC <= 2.34)
- lib/libstdc++.so.6: conda-forge libstdcxx-ng 12.2.0 (GCC runtime library exception), provides GLIBCXX_3.4.30
