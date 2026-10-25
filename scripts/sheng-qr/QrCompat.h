#pragma once
#include <Uefi.h>
#include <Library/BaseLib.h>
#include <Library/BaseMemoryLib.h>
#include <Library/DebugLib.h>

// 二维码库只使用整数和内存操作，无须引入宿主 C 运行时。
typedef BOOLEAN bool;
typedef UINT8 uint8_t;
typedef INT8 int8_t;
typedef UINTN size_t;
#define true TRUE
#define false FALSE
#define SIZE_MAX MAX_UINTN
#define INT16_MAX 32767
#define LONG_MAX __LONG_MAX__
#define assert(Value) ASSERT(Value)
#define strlen(Value) AsciiStrLen(Value)
// 搜索范围包含结尾零字节，保留标准 strchr 对空字符的行为。
#define strchr(Value, Character) ((CONST CHAR8 *)ScanMem8(Value, AsciiStrSize(Value), (UINT8)(Character)))
#define memcpy(Dest, Source, Size) CopyMem(Dest, Source, Size)
#define memmove(Dest, Source, Size) CopyMem(Dest, Source, Size)
#define memset(Dest, Value, Size) SetMem(Dest, Size, (UINT8)(Value))
#define abs(Value) (((Value) < 0) ? -(Value) : (Value))
#define labs(Value) abs(Value)
