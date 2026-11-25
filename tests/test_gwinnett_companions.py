from io import BytesIO
from zipfile import ZipFile

import pytest

from cre.ingestion.contract import SnapshotError
from cre.ingestion.gwinnett_companions import source_keys


def key_book(last_number):
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    data = BytesIO()
    with ZipFile(data, "w") as book:
        book.writestr(
            "xl/sharedStrings.xml",
            f'<sst xmlns="{ns}"><si><t>PIN</t></si><si><t>LRSNum</t></si>'
            "<si><t>LRSN</t></si><si><t>001 A-2</t></si></sst>",
        )
        book.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{ns}"><sheetData><row r="1">'
            '<c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>'
            '<c r="C1" t="s"><v>2</v></c></row><row r="3">'
            '<c r="A3" t="s"><v>3</v></c><c r="B3"><v>12</v></c>'
            f'<c r="C3"><v>{last_number}</v></c></row></sheetData></worksheet>',
        )
    return data.getvalue()


def test_original_row_and_source_pin_are_preserved():
    with source_keys(key_book(12), 3, corroborate=True) as (headers, rows):
        assert headers == ["PIN", "LRSNum", "LRSN"]
        assert list(rows) == [(3, "001 A-2", 12)]


def test_conflicting_secondary_key_requires_review():
    with (
        source_keys(key_book(14), 3, corroborate=True) as (_, rows),
        pytest.raises(SnapshotError, match="inconsistent"),
    ):
        list(rows)
