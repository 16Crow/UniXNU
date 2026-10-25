#include <Library/PrintLib.h>

STATIC EFI_GUID mShengDiagGuid = {0xe5f041db,0x038d,0x4af9,{0xa9,0xbb,0x48,0xe7,0x2a,0xde,0x11,0xa0}};
STATIC CHAR8 mShengDiagText[2048]; // 保留关键内存日志，供菜单阶段生成二维码。
STATIC UINTN mShengDiagUsed;

STATIC VOID
ShengDiagLog (CONST CHAR8 *Format, ...)
{
  // 复用同一份格式化结果，避免屏幕文字和二维码诊断不一致。
  VA_LIST Args;
  CHAR8 Line[256];
  UINTN Available;
  VA_START (Args, Format);
  AsciiVSPrint (Line, sizeof (Line), Format, Args);
  VA_END (Args);
  DEBUG ((DEBUG_ERROR, "%a", Line));
  Available = sizeof (mShengDiagText) - mShengDiagUsed;
  if (Available > 1) {
    mShengDiagUsed += AsciiSPrint (mShengDiagText + mShengDiagUsed, Available, "%a", Line);
  }
}
