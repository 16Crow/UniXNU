#!/usr/bin/env python3
"""给指定 sheng 诊断构建注入日志二维码，保持正常构建路径不变。"""
from pathlib import Path
import re
import shutil
import sys


def replace_once(path, old, new):
    # 上游结构变化时直接停下，避免悄悄漏掉日志采集或诊断入口。
    text = path.read_text()
    if new in text:
        return
    if text.count(old) != 1:
        raise RuntimeError(f'Unexpected source anchor in {path}: {old}')
    path.write_text(text.replace(old, new))


def prepare(uefi):
    # 在源码树组装前注入模块，固件和应用才能共享同一份日志表。
    root = Path(__file__).resolve().parent.parent
    overlays = root / 'scripts/sheng-qr'
    driver = uefi / 'Platforms/Xiaomi/shengPkg/Drivers/ShengBootMemoryDxe'
    lib = root / 'package/UniXNUPkg/Library/UniXNULib'
    shutil.copy2(overlays / 'ShengDiagLog.h', driver)
    source = driver / 'ShengBootMemoryDxe.c'
    text = source.read_text()
    text = re.sub(r'DEBUG \(\(DEBUG_ERROR, ("SHENGMEM:[^\n]+?)\)\);', r'ShengDiagLog (\1);', text)
    if '#include "ShengDiagLog.h"' not in text:
        text = '#include <Uefi.h>\n#include <Library/UefiBootServicesTableLib.h>\n#include <Library/DebugLib.h>\n#include "ShengDiagLog.h"\n' + text
    source.write_text(text)
    replace_once(source, '  Hob = GetFirstGuidHob (&gSiliciumEntryArgHobGuid);',
                 '  gBS->InstallConfigurationTable (&mShengDiagGuid, mShengDiagText);\n  Hob = GetFirstGuidHob (&gSiliciumEntryArgHobGuid);')
    replace_once(driver / 'ShengBootMemoryDxe.inf', '  BaseLib\n', '  BaseLib\n  PrintLib\n')
    for name in ('DiagnosticQr.c', 'QrCompat.h', 'qrcodegen.c', 'qrcodegen.h'):
        shutil.copy2(overlays / name, lib / name)
    replace_once(lib / 'UniXNULib.inf', '  Main.c\n', '  Main.c\n  DiagnosticQr.c\n  qrcodegen.c\n')
    replace_once(lib / 'Main.c', '#include "Internal.h"', '#include "Internal.h"\nVOID UniXNUShowDiagnosticQr (UNIXNU_CONFIG *Config);')
    replace_once(lib / 'Main.c', '  UniXNUConfigLoad (ImageHandle, &Config);',
                 '  UniXNUConfigLoad (ImageHandle, &Config);\n  UniXNUShowDiagnosticQr (&Config);')
    print('Prepared sheng QR diagnostics: key memory logs, builtin config, persistent paged QR')


if __name__ == '__main__':
    prepare(Path(sys.argv[1]).resolve())
