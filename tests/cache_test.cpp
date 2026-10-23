#include "cache.h"
#include <cassert>
#include <sstream>
#include <iostream>

int main() {
    Cache lru(256, 64, 4, ReplacementPolicy::Lru);
    for (unsigned i = 0; i < 4; ++i) assert(!lru.accessBlock(i * 64));
    assert(lru.accessBlock(0));
    assert(!lru.accessBlock(256));
    assert(lru.accessBlock(128));
    assert(!lru.accessBlock(64));

    // After saturation bit-PLRU keeps only the most recent way's MRU bit.
    // This sequence distinguishes it from tree-PLRU (which evicts way 2).
    Cache bit(256, 64, 4, ReplacementPolicy::Plru);
    for (unsigned i = 0; i < 4; ++i) assert(!bit.accessBlock(i * 64));
    assert(bit.accessBlock(0));
    assert(!bit.accessBlock(256));
    assert(bit.accessBlock(128));
    assert(!bit.accessBlock(64));

    Cache random1(256, 64, 4, ReplacementPolicy::Random);
    Cache random2(256, 64, 4, ReplacementPolicy::Random);
    for (unsigned i = 0; i < 1000; ++i) {
        uintptr_t address = ((i * 7) % 13) * 64;
        assert(random1.accessBlock(address) == random2.accessBlock(address));
    }
    // Direct mapping must behave identically for all replacement policies.
    Cache direct(128, 64, 1, ReplacementPolicy::Lru);
    Cache directBit(128, 64, 1, ReplacementPolicy::Plru);
    for (unsigned i = 0; i < 100; ++i)
        assert(direct.accessBlock(i * 64) == directBit.accessBlock(i * 64));

    mhInit(128, 64, 1, "lru", 0, 64, 1, "lru");
    mhLoad(reinterpret_cast<void*>(60), 8, 0); // Two blocks, two DRAM misses.
    mhStore(reinterpret_cast<void*>(60), 8, 0); // Two write hits.
    mhLoad(reinterpret_cast<void*>(60), 0, 0); // Zero-sized access is ignored.
    std::ostringstream one;
    mhPrintStats(one);
    assert(one.str().find("accesses: 4\n") != std::string::npos);
    assert(one.str().find("misses: 2\n") != std::string::npos);
    assert(one.str().find("write_hits: 2\n") != std::string::npos);
    assert(one.str().find("dram_accesses: 2\n") != std::string::npos);

    mhInit(128, 64, 1, "lru", 256, 128, 1, "plru");
    mhLoad(reinterpret_cast<void*>(0), 1, 0); // Both levels miss.
    mhLoad(reinterpret_cast<void*>(64), 1, 0); // L1 miss, shared L2 line hits.
    mhLoad(reinterpret_cast<void*>(0), 1, 0); // L1 hits.
    std::ostringstream two;
    mhPrintStats(two);
    assert(two.str().find("l2_accesses: 2\n") != std::string::npos);
    assert(two.str().find("l2_hits: 1\n") != std::string::npos);
    assert(two.str().find("dram_accesses: 1\n") != std::string::npos);
    std::cout << "Cache tests passed\n";
}
