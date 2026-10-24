#!/usr/bin/env python3
"""修正 sheng 固件中与源码构建清单不一致的启动顺序引用。"""
from pathlib import Path
import sys


def prepare(uefi):
    # APRIORI 只控制加载顺序，应指向 DSC 与 DXE 清单使用的同一个模块。
    source = 'MdeModulePkg/Universal/DevicePathDxe/DevicePathDxe.inf'
    legacy = 'Binaries/sheng/' + source
    include = uefi / 'Platforms/Xiaomi/shengPkg/Include'
    apriori = include / 'APRIORI.inc'
    text = apriori.read_text()
    dxe = (include / 'DXE.inc').read_text()
    common = (uefi / 'Silicon/Silicium/SiliciumPkg/SiliciumPkg.dsc.inc').read_text()
    if 'INF ' + source not in dxe or source not in common:
        raise SystemExit('DevicePathDxe source is absent from the firmware build inputs')
    if text.count(legacy) == 1:
        apriori.write_text(text.replace(legacy, source))
        print('Corrected sheng APRIORI to use the existing source DevicePathDxe')
    elif legacy not in text and text.count('INF ' + source) == 1:
        print('sheng APRIORI already uses source DevicePathDxe')
    else:
        raise SystemExit('Unexpected DevicePathDxe APRIORI entries; refusing an ambiguous edit')


if __name__ == '__main__':
    prepare(Path(sys.argv[1]).resolve())
