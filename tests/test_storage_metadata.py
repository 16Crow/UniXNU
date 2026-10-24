"""存储审计必须使用本次编译出的元类布局。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from storage_metadata import metaclass_layout


class MetaclassLayout(unittest.TestCase):
    # 构造 dwarfdump 成员记录，覆盖缺字段、版本变化及同名冲突。
    def dwarf(self, fields):
        return '\n'.join(
            f'DW_TAG_member\n DW_AT_name ("{name}")\n DW_AT_data_member_location (0x{offset:x})'
            for name, offset in fields)

    def test_real_expected_layout_with_unrelated_members(self):
        fields = [('superClassLink', 16), ('className', 24), ('classSize', 32), ('other', 40)]
        self.assertEqual(metaclass_layout(self.dwarf(fields)),
                         dict(superClassLink=16, className=24, classSize=32))

    def test_missing_member_is_not_filled_from_defaults(self):
        with self.assertRaisesRegex(ValueError, 'layout'):
            metaclass_layout(self.dwarf([('className', 24), ('classSize', 32)]))

    def test_changed_abi_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'layout'):
            metaclass_layout(self.dwarf([('superClassLink', 8), ('className', 24), ('classSize', 32)]))

    def test_conflicting_records_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            metaclass_layout(self.dwarf([('superClassLink', 8), ('superClassLink', 16),
                                         ('className', 24), ('classSize', 32)]))


if __name__ == '__main__':
    unittest.main()
