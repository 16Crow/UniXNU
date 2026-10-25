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
#define assert(Value) ASSERT(Value)
#define strlen(Value) AsciiStrLen(Value)
#define memcpy(Dest, Source, Size) CopyMem(Dest, Source, Size)
#define memmove(Dest, Source, Size) CopyMem(Dest, Source, Size)
#define memset(Dest, Value, Size) SetMem(Dest, Size, (UINT8)(Value))
#define abs(Value) (((Value) < 0) ? -(Value) : (Value))
#define labs(Value) abs(Value)
