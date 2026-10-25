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

STATIC VOID
ShengDiagDumpHex (
  IN CONST CHAR8  *Label,
  IN CONST VOID   *Base,
  IN UINTN        Length
  )
{
  // 关键判别证据：initrd 开头/结尾字节区分 FAT 卷（eb 3c 90 4d 53 44 4f 53）
  // 与安卓 vendor ramdisk（1f 8b gzip 或 30 37 30 37 cpio，尾部 TRAILER!!!）。
  // 手工查表生成十六进制，不依赖 PrintLib 的宽度/补零支持。
  STATIC CONST CHAR8  HexDigits[] = "0123456789abcdef";
  CONST UINT8         *Bytes;
  CHAR8               Line[112];
  UINTN               Index;
  UINTN               Used;

  Bytes = Base;
  Used  = 0;
  for (Index = 0; (Index < Length) && (Used + 4 < sizeof (Line)); Index++) {
    Line[Used++] = HexDigits[Bytes[Index] >> 4];
    Line[Used++] = HexDigits[Bytes[Index] & 0x0f];
    Line[Used++] = ' ';
  }
  Line[Used] = '\0';
  ShengDiagLog ("SHENGMEM: %a %a\n", Label, Line);
}
