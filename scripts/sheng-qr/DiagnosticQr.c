/** sheng 缺失配置时停留显示诊断二维码，不启动内核或修改分区。 */
#include "Internal.h"
#include "qrcodegen.h"
#include <Protocol/BlockIo.h>

STATIC EFI_GUID mShengDiagGuid = {0xe5f041db,0x038d,0x4af9,{0xa9,0xbb,0x48,0xe7,0x2a,0xde,0x11,0xa0}};
#define DIAG_PAGE_BYTES 550
#define DIAG_QR_VERSION 20

STATIC BOOLEAN
DrawDiagnosticQr (EFI_GRAPHICS_OUTPUT_PROTOCOL *Gop, CONST CHAR8 *Text)
{
  // 单次 GOP 绘制保留四模块白边；黑白色不依赖 RGB/BGR 排列。
  UINT8 Temp[qrcodegen_BUFFER_LEN_FOR_VERSION(DIAG_QR_VERSION)];
  UINT8 Code[qrcodegen_BUFFER_LEN_FOR_VERSION(DIAG_QR_VERSION)];
  EFI_GRAPHICS_OUTPUT_BLT_PIXEL *Pixels;
  EFI_STATUS Status;
  UINTN Modules, Scale, Side, X, Y, Width, Height;
  if (!qrcodegen_encodeText (Text, Temp, Code, qrcodegen_Ecc_MEDIUM,
                            1, DIAG_QR_VERSION, qrcodegen_Mask_AUTO, true)) {
    return FALSE;
  }
  Width = Gop->Mode->Info->HorizontalResolution;
  Height = Gop->Mode->Info->VerticalResolution;
  Modules = (UINTN)qrcodegen_getSize (Code);
  Scale = MIN (Width, Height) * 3 / 4 / (Modules + 8);
  if (Scale == 0) {
    return FALSE;
  }
  Side = (Modules + 8) * Scale;
  Pixels = AllocatePool (Side * Side * sizeof (*Pixels));
  if (Pixels == NULL) {
    return FALSE;
  }
  SetMem (Pixels, Side * Side * sizeof (*Pixels), 0xFF);
  for (Y = 4 * Scale; Y < (Modules + 4) * Scale; Y++) {
    for (X = 4 * Scale; X < (Modules + 4) * Scale; X++) {
      if (qrcodegen_getModule (Code, (int)(X / Scale - 4), (int)(Y / Scale - 4))) {
        ZeroMem (&Pixels[Y * Side + X], sizeof (*Pixels));
      }
    }
  }
  Status = Gop->Blt (Gop, Pixels, EfiBltBufferToVideo, 0, 0,
                    (Width - Side) / 2, (Height - Side) / 2, Side, Side, 0);
  FreePool (Pixels);
  return !EFI_ERROR (Status);
}

VOID
UniXNUShowDiagnosticQr (UNIXNU_CONFIG *Config)
{
  // 仅识别专用诊断固件发布的日志表，其他平台和正常配置沿用原菜单。
  EFI_GRAPHICS_OUTPUT_PROTOCOL *Gop;
  EFI_INPUT_KEY Key;
  CHAR8 *MemoryLog;
  CHAR8 Text[3072];
  CHAR8 Page[DIAG_PAGE_BYTES + 96];
  EFI_STATUS Status;
  EFI_HANDLE *Handles;
  UINTN Blocks, Volumes, Length, Pages, Index, Offset, Count, Tick;
  if (Config->Volume != NULL ||
      EFI_ERROR (EfiGetSystemConfigurationTable (&mShengDiagGuid, (VOID **)&MemoryLog)) ||
      MemoryLog == NULL || EFI_ERROR (gBS->LocateProtocol (&gEfiGraphicsOutputProtocolGuid, NULL, (VOID **)&Gop)) ||
      Gop->Mode == NULL || Gop->Mode->Info == NULL) {
    return;
  }
  Handles = NULL;
  Blocks = Volumes = 0;
  Status = gBS->LocateHandleBuffer (ByProtocol, &gEfiBlockIoProtocolGuid, NULL, &Blocks, &Handles);
  if (!EFI_ERROR (Status)) { FreePool (Handles); }
  Handles = NULL;
  Status = gBS->LocateHandleBuffer (ByProtocol, &gEfiSimpleFileSystemProtocolGuid, NULL, &Volumes, &Handles);
  if (!EFI_ERROR (Status)) { FreePool (Handles); }
  AsciiSPrint (Text, sizeof (Text), "SHENG-DIAG-QR-v1\nconfig=builtin\nblocks=%u filesystems=%u\nerror=%a\nnotice=%a\n%a",
              (UINT32)Blocks, (UINT32)Volumes, Config->Error, Config->Notice, MemoryLog);
  Length = AsciiStrLen (Text);
  Pages = (Length + DIAG_PAGE_BYTES - 1) / DIAG_PAGE_BYTES;
  // 诊断页一直循环，每页停留 30 秒；避免 10 秒自动退出丢失证据。
  for (Index = 0; ; Index = (Index + 1) % Pages) {
    Offset = Index * DIAG_PAGE_BYTES;
    Count = MIN (Length - Offset, DIAG_PAGE_BYTES);
    AsciiSPrint (Page, sizeof (Page), "SHENG-DIAG page=%u/%u offset=%u\n", (UINT32)Index + 1, (UINT32)Pages, (UINT32)Offset);
    Offset = AsciiStrLen (Page);
    CopyMem (Page + Offset, Text + Index * DIAG_PAGE_BYTES, Count);
    Page[Offset + Count] = '\0';
    gST->ConOut->ClearScreen (gST->ConOut);
    Print (L"SHENG diagnostics QR  %u/%u\r\nPhotograph each page. Changes every 30 seconds.\r\nPress a key to return to the menu.\r\n", (UINT32)Index + 1, (UINT32)Pages);
    if (!DrawDiagnosticQr (Gop, Page)) {
      Print (L"QR drawing failed.\r\n%a\r\n", Text);
    }
    for (Tick = 0; Tick < 300; Tick++) {
      if (gST->ConIn != NULL && !EFI_ERROR (gST->ConIn->ReadKeyStroke (gST->ConIn, &Key))) {
        return;
      }
      gBS->Stall (100000);
    }
  }
}
