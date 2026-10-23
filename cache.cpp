#include "cache.h"

#include <algorithm>
#include <ostream>
#include <string>
#include <cstdlib>
#include <iostream>

static void invalidConfig(const char* message) {
    std::cerr << "Cache configuration error: " << message << '\n';
    std::exit(1);
}

ReplacementPolicy parseReplacementPolicy(const std::string& name) {
    if (name == "random") return ReplacementPolicy::Random;
    if (name == "lru") return ReplacementPolicy::Lru;
    if (name == "plru" || name == "bit-plru") return ReplacementPolicy::Plru;
    if (name == "round-robin" || name == "rr") return ReplacementPolicy::RoundRobin;
    invalidConfig("unknown replacement policy");
    return ReplacementPolicy::Lru;
}

Cache::Cache(std::size_t capacityBytes, std::size_t blockSizeBytes,
             std::size_t associativity, ReplacementPolicy policy)
    : capacityBytes_(capacityBytes), blockSizeBytes_(blockSizeBytes),
      associativity_(associativity), numberOfSets_(0), policy_(policy),
      randomState_(0x4472026u) {
    if (capacityBytes_ == 0 || blockSizeBytes_ == 0 || associativity_ == 0 ||
        capacityBytes_ % blockSizeBytes_ != 0 ||
        (capacityBytes_ / blockSizeBytes_) % associativity_ != 0) {
        invalidConfig("capacity must be divisible by block size and associativity");
    }
    numberOfSets_ = capacityBytes_ / blockSizeBytes_ / associativity_;
    if ((numberOfSets_ & (numberOfSets_ - 1)) != 0 ||
        (associativity_ & (associativity_ - 1)) != 0 ||
        (blockSizeBytes_ & (blockSizeBytes_ - 1)) != 0) {
        invalidConfig("sets, ways, and block size must be powers of two");
    }
    sets_.assign(numberOfSets_, std::vector<CacheLine>(associativity_));
    nextVictim_.assign(numberOfSets_, 0);
    lruOrder_.resize(numberOfSets_);
    plruBits_.resize(numberOfSets_);
    for (std::size_t set = 0; set < numberOfSets_; ++set) {
        for (std::size_t way = 0; way < associativity_; ++way) lruOrder_[set].push_back(way);
        plruBits_[set].assign(associativity_, false);
    }
}

std::size_t Cache::setIndex(uintptr_t blockAddress) const {
    return static_cast<std::size_t>(blockAddress % numberOfSets_);
}

uint64_t Cache::tag(uintptr_t blockAddress) const {
    return static_cast<uint64_t>(blockAddress / numberOfSets_);
}

void Cache::touch(std::size_t set, std::size_t way) {
    if (policy_ == ReplacementPolicy::Lru) {
        std::vector<std::size_t>& order = lruOrder_[set];
        order.erase(std::find(order.begin(), order.end(), way));
        order.push_back(way);
    } else if (policy_ == ReplacementPolicy::Plru && associativity_ > 1) {
        // Bit-PLRU: one MRU bit per way. On saturation clear all other bits.
        plruBits_[set][way] = true;
        if (std::find(plruBits_[set].begin(), plruBits_[set].end(), false) == plruBits_[set].end()) {
            std::fill(plruBits_[set].begin(), plruBits_[set].end(), false);
            plruBits_[set][way] = true;
        }
    }
}

std::size_t Cache::chooseVictim(std::size_t set) {
    for (std::size_t way = 0; way < associativity_; ++way)
        if (!sets_[set][way].valid) return way;
    if (policy_ == ReplacementPolicy::Random) {
        // xorshift32 avoids the alternating low bits of the previous LCG.
        randomState_ ^= randomState_ << 13;
        randomState_ ^= randomState_ >> 17;
        randomState_ ^= randomState_ << 5;
        return static_cast<std::size_t>(randomState_ % associativity_);
    }
    if (policy_ == ReplacementPolicy::Lru) return lruOrder_[set].front();
    if (policy_ == ReplacementPolicy::Plru && associativity_ > 1) {
        return static_cast<std::size_t>(std::find(plruBits_[set].begin(), plruBits_[set].end(), false) - plruBits_[set].begin());
    }
    const std::size_t victim = nextVictim_[set];
    nextVictim_[set] = (victim + 1) % associativity_;
    return victim;
}

bool Cache::accessBlock(uintptr_t address, bool write) {
    const uintptr_t blockAddress = address / blockSizeBytes_;
    const std::size_t set = setIndex(blockAddress);
    const uint64_t cacheTag = tag(blockAddress);
    ++stats_.accesses;
    if (write) ++stats_.writes; else ++stats_.reads;
    for (std::size_t way = 0; way < associativity_; ++way) {
        if (sets_[set][way].valid && sets_[set][way].tag == cacheTag) {
            ++stats_.hits;
            if (write) ++stats_.writeHits; else ++stats_.readHits;
            touch(set, way);
            return true;
        }
    }
    ++stats_.misses;
    const std::size_t victim = chooseVictim(set);
    sets_[set][victim].valid = true;
    sets_[set][victim].tag = cacheTag;
    touch(set, victim);
    return false;
}

void Cache::access(uintptr_t address, std::size_t size) {
    if (size == 0) return;
    const uintptr_t end = address + size - 1;
    for (uintptr_t current = address;;) {
        accessBlock(current);
        const uintptr_t next = ((current / blockSizeBytes_) + 1) * blockSizeBytes_;
        if (next > end || next <= current) break;
        current = next;
    }
}

void Cache::printStats(std::ostream& out, const char* prefix) const {
    out << prefix << "accesses: " << stats_.accesses << '\n'
        << prefix << "hits: " << stats_.hits << '\n'
        << prefix << "misses: " << stats_.misses << '\n'
        << prefix << "reads: " << stats_.reads << '\n'
        << prefix << "writes: " << stats_.writes << '\n'
        << prefix << "read_hits: " << stats_.readHits << '\n'
        << prefix << "write_hits: " << stats_.writeHits << '\n'
        << prefix << "miss_rate: "
        << (stats_.accesses ? static_cast<double>(stats_.misses) / stats_.accesses : 0.0) << '\n';
}

static Cache* l1 = 0;
static Cache* l2 = 0;
static HierarchyStats hierarchyStats;

void mhInit(std::size_t l1CapacityBytes, std::size_t l1BlockSize,
            std::size_t l1Associativity, const std::string& l1Replacement,
            std::size_t l2CapacityBytes, std::size_t l2BlockSize,
            std::size_t l2Associativity, const std::string& l2Replacement) {
    if (l1BlockSize == 0 || (l2CapacityBytes &&
        (l2BlockSize == 0 || l2BlockSize < l1BlockSize || l2BlockSize % l1BlockSize)))
        invalidConfig("L2 blocks must be a multiple of and at least as large as L1 blocks");
    delete l1; delete l2;
    l1 = new Cache(l1CapacityBytes, l1BlockSize, l1Associativity, parseReplacementPolicy(l1Replacement));
    l2 = (l2CapacityBytes == 0) ? 0 : new Cache(l2CapacityBytes, l2BlockSize, l2Associativity, parseReplacementPolicy(l2Replacement));
    hierarchyStats = HierarchyStats();
}

static void hierarchyAccess(uintptr_t address, std::size_t size, bool write) {
    if (!l1 || size == 0) return;
    const uintptr_t end = address + size - 1;
    for (uintptr_t current = address;;) {
        if (!l1->accessBlock(current, write)) {
            if (!l2 || !l2->accessBlock(current)) ++hierarchyStats.dramAccesses;
        }
        const uintptr_t next = ((current / l1->blockSize()) + 1) * l1->blockSize();
        if (next > end || next <= current) break;
        current = next;
    }
}

void mhLoad(void* addr, std::size_t size, void*) { hierarchyAccess(reinterpret_cast<uintptr_t>(addr), size, false); }
void mhStore(void* addr, std::size_t size, void*) { hierarchyAccess(reinterpret_cast<uintptr_t>(addr), size, true); }

void mhPrintStats(std::ostream& out) {
    if (l1) l1->printStats(out, "");
    if (l2) l2->printStats(out, "l2_");
    out << "dram_accesses: " << hierarchyStats.dramAccesses << '\n';
}
