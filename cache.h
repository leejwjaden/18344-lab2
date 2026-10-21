#pragma once

#include <cstddef>
#include <stdint.h>
#include <iosfwd>
#include <string>
#include <vector>

struct CacheLine {
    bool valid;
    uint64_t tag;
    CacheLine() : valid(false), tag(0) {}
};

struct CacheStats {
    uint64_t accesses;
    uint64_t hits;
    uint64_t misses;
    CacheStats() : accesses(0), hits(0), misses(0) {}
};

enum class ReplacementPolicy { Random, Lru, Plru, RoundRobin };
ReplacementPolicy parseReplacementPolicy(const std::string& name);

class Cache {
public:
    Cache(std::size_t capacityBytes, std::size_t blockSizeBytes,
          std::size_t associativity, ReplacementPolicy policy);

    bool accessBlock(uintptr_t address);
    void access(uintptr_t address, std::size_t size);
    const CacheStats& stats() const { return stats_; }
    void printStats(std::ostream& out, const char* prefix = "") const;
    std::size_t blockSize() const { return blockSizeBytes_; }

private:
    std::size_t setIndex(uintptr_t blockAddress) const;
    uint64_t tag(uintptr_t blockAddress) const;
    std::size_t chooseVictim(std::size_t set);
    void touch(std::size_t set, std::size_t way);

    std::size_t capacityBytes_;
    std::size_t blockSizeBytes_;
    std::size_t associativity_;
    std::size_t numberOfSets_;
    ReplacementPolicy policy_;
    std::vector<std::vector<CacheLine> > sets_;
    std::vector<std::vector<std::size_t> > lruOrder_;
    std::vector<std::size_t> nextVictim_;
    std::vector<std::vector<bool> > plruBits_;
    uint32_t randomState_;
    CacheStats stats_;
};

struct HierarchyStats {
    uint64_t dramAccesses;
    HierarchyStats() : dramAccesses(0) {}
};

void mhInit(std::size_t l1CapacityBytes, std::size_t l1BlockSize,
            std::size_t l1Associativity, const std::string& l1Replacement,
            std::size_t l2CapacityBytes, std::size_t l2BlockSize,
            std::size_t l2Associativity, const std::string& l2Replacement);
void mhPrintStats(std::ostream& out);
void mhLoad(void* addr, std::size_t size, void* instAddr);
void mhStore(void* addr, std::size_t size, void* instAddr);
