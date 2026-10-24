"""从实际编译对象的 DWARF 信息确认存储审计使用的元类布局。"""
import re


def metaclass_layout(dwarf):
    # 布局必须来自当前对象；缺字段或版本变化时不能用预设值补齐。
    expected = dict(superClassLink=16, className=24, classSize=32)
    layout = {}
    for member in dwarf.split('DW_TAG_member')[1:]:
        name = re.search(r'DW_AT_name\s+\("([^"]+)"\)', member)
        offset = re.search(r'DW_AT_data_member_location\s+\((0x[0-9a-f]+)\)', member)
        if not name or not offset or name[1] not in expected:
            continue
        field, value = name[1], int(offset[1], 16)
        if field in layout and layout[field] != value:
            raise ValueError(f'conflicting OSMetaClass layout for {field}')
        layout[field] = value
    if layout != expected:
        raise ValueError(f'Unexpected compiled OSMetaClass layout: {layout}')
    return layout
