"""Save an openpyxl workbook with its formulas AND their current values.

openpyxl writes formulas with no cached value, so anything that reads values
(pandas, previews, most viewers) sees empty cells until Excel recalculates.
The run sandbox has no LibreOffice to recalculate, so the scripts compute each
formula's value in Python and this module writes it into the cell beside the
formula. Excel still recalculates on open (fullCalcOnLoad).
"""
import os
import re
import shutil
import tempfile
import zipfile
from datetime import date, datetime
from xml.sax.saxutils import escape

EPOCH = date(1899, 12, 30)


def _v(value):
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return "", str((value - EPOCH).days)
    if isinstance(value, bool):
        return ' t="b"', "1" if value else "0"
    if isinstance(value, (int, float)):
        return "", repr(float(value)) if isinstance(value, float) else str(value)
    return ' t="str"', escape(str(value))


def save_with_values(wb, path, cache):
    """cache: {sheet_name: {"B6": value, ...}} for formula cells."""
    wb.calculation.fullCalcOnLoad = True
    wb.save(path)
    files = {f"xl/worksheets/sheet{i + 1}.xml": cache.get(name, {}) for i, name in enumerate(wb.sheetnames)}
    fd, tmp = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            values = files.get(item.filename)
            if values:
                xml = data.decode("utf-8")

                def fill(m):
                    coord = m.group(1)
                    if coord not in values or values[coord] is None:
                        return m.group(0)
                    t, v = _v(values[coord])
                    attrs = re.sub(r'\s+t="[^"]*"', "", m.group(2))
                    return f'<c r="{coord}"{attrs}{t}><f>{m.group(3)}</f><v>{v}</v></c>'

                xml = re.sub(r'<c r="([A-Z]+[0-9]+)"([^>]*)><f>(.*?)</f><v\s*/?>(?:</v>)?</c>', fill, xml)
                data = xml.encode("utf-8")
            zout.writestr(item, data)
    shutil.move(tmp, path)
