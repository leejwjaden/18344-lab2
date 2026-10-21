/*
 * Copyright 2002-2020 Intel Corporation.
 * 
 * This software is provided to you as Sample Source Code as defined in the accompanying
 * End User License Agreement for the Intel(R) Software Development Products ("Agreement")
 * section 1.L.
 * 
 * This software and the related documents are provided as is, with no express or implied
 * warranties, other than those that are expressly stated in the License.
 */

/*! @file
 *  This file contains an ISA-portable cache simulator
 *  data cache hierarchies
 */


#include "pin.H"

#include <iostream>
#include <fstream>
#include <cassert>

#include "cache.h"

using std::cerr;
using std::endl;
using std::string;

/* ===================================================================== */
/* Commandline Switches */
/* ===================================================================== */

KNOB<string> KnobOutputFile(KNOB_MODE_WRITEONCE,    "pintool",
    "o", "memhier.stats", "specify dcache file name");
KNOB<UINT32> KnobL1CacheSize(KNOB_MODE_WRITEONCE, "pintool",
    "l1c","2", "cache size in kilobytes");
KNOB<UINT32> KnobL1LineSize(KNOB_MODE_WRITEONCE, "pintool",
    "l1b","64", "cache block size in bytes");
KNOB<UINT32> KnobL1Associativity(KNOB_MODE_WRITEONCE, "pintool",
    "l1a","2", "cache associativity (1 for direct mapped)");

KNOB<UINT32> KnobL2CacheSize(KNOB_MODE_WRITEONCE, "pintool",
    "l2c", "0", "L2 cache size in kilobytes (0 disables L2)");
KNOB<UINT32> KnobL2LineSize(KNOB_MODE_WRITEONCE, "pintool",
    "l2b", "64", "L2 cache block size in bytes");
KNOB<UINT32> KnobL2Associativity(KNOB_MODE_WRITEONCE, "pintool",
    "l2a", "8", "L2 cache associativity");
KNOB<string> KnobL1Replacement(KNOB_MODE_WRITEONCE, "pintool",
    "l1r", "lru", "L1 replacement policy");
KNOB<string> KnobL2Replacement(KNOB_MODE_WRITEONCE, "pintool",
    "l2r", "lru", "L2 replacement policy");

/* ===================================================================== */

INT32 Usage()
{
    cerr <<
        "This tool is a cache simulator.\n"
        "\n";

    cerr << KNOB_BASE::StringKnobSummary();

    cerr << endl;

    return -1;
}

/* ===================================================================== */

VOID Load(ADDRINT addr, UINT32 size, ADDRINT instAddr)
{
  mhLoad((void*)addr,size,(void*)instAddr);
}

/* ===================================================================== */

VOID Store(ADDRINT addr, UINT32 size, ADDRINT instAddr)
{
  mhStore((void*)addr,size,(void*)instAddr);
}


/* ===================================================================== */

VOID Instruction(INS ins, void * v)
{
    UINT32 memOperands = INS_MemoryOperandCount(ins);

    // Instrument each memory operand. If the operand is both read and written
    // it will be processed twice.
    // Iterating over memory operands ensures that instructions on IA-32 with
    // two read operands (such as SCAS and CMPS) are correctly handled.
    for (UINT32 memOp = 0; memOp < memOperands; memOp++)
    {
        const UINT32 size = INS_MemoryOperandSize(ins, memOp);
        
        if (INS_MemoryOperandIsRead(ins, memOp))
        {
                // map sparse INS addresses to dense IDs
          const ADDRINT iaddr = INS_Address(ins);

          INS_InsertPredicatedCall(
                        ins, IPOINT_BEFORE,  (AFUNPTR) Load,
                        IARG_MEMORYOP_EA, memOp,
                        IARG_UINT32, size,
                        IARG_ADDRINT, iaddr,
                        IARG_END);
        }
        
        if (INS_MemoryOperandIsWritten(ins, memOp))
        {
          const ADDRINT iaddr = INS_Address(ins);

          INS_InsertPredicatedCall(
                        ins, IPOINT_BEFORE,  (AFUNPTR) Store,
                        IARG_MEMORYOP_EA,memOp,
                        IARG_UINT32, size,
                        IARG_ADDRINT, iaddr,
                        IARG_END);
        }
    }
}

/* ===================================================================== */

VOID Fini(int code, VOID * v)
{

    std::ofstream out(KnobOutputFile.Value().c_str());

    mhPrintStats(out);
    out.close();
}

/* ===================================================================== */

int main(int argc, char *argv[])
{
    PIN_InitSymbols();

    if( PIN_Init(argc,argv) )
    {
        return Usage();
    }

    mhInit(static_cast<std::size_t>(KnobL1CacheSize.Value()) * 1024,
           KnobL1LineSize.Value(), KnobL1Associativity.Value(), KnobL1Replacement.Value(),
           static_cast<std::size_t>(KnobL2CacheSize.Value()) * 1024,
           KnobL2LineSize.Value(), KnobL2Associativity.Value(), KnobL2Replacement.Value());
    INS_AddInstrumentFunction(Instruction, 0);
    PIN_AddFiniFunction(Fini, 0);

    // Never returns

    PIN_StartProgram();
    
    return 0;
}

/* ===================================================================== */
/* eof */
/* ===================================================================== */
