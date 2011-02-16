# Classes for working with the textual table output from gdb-heap

import unittest
import re
from collections import namedtuple

def indent(str_):
    return '\n'.join([(' ' * 4) + line
                      for line in str_.splitlines()])

class ColumnNotFound(Exception):
    def __init__(self, colname, table):
        self.colname = colname
        self.table = table

    def __str__(self):
        return ('ColumnNotFound(%s) in:\n%s'
                % (self.colname, indent(str(self.table))))

class RowNotFound(Exception):
    def __init__(self, criteria, table):
        self.criteria = criteria
        self.table = table
    def __str__(self):
        return ('RowNotFound(%s) in:\n%s'
                % (self.criteria, indent(str(self.table))))

class Criteria(object):
    '''A list of (colname, value) criteria for searching rows in a table'''
    def __init__(self, table, kvs):
        self.kvs = kvs
        self._by_index = [(table.find_col(attrname), value)
                          for attrname, value in kvs]

    def __str__(self):
        return 'Criteria(%s)' % ','.join('%r=%r' % (attrname, value)
                                         for attrname, value in self.kvs)

    def is_matched_by(self, row):
        for colindex, value in self._by_index:
            if row[colindex] != value:
                return False
        return True


class ParsedTable(object):
    '''Parses output from heap.Table, for use in writing selftests'''
    @classmethod
    def parse_lines(cls, data):
        '''Parse the lines in the string, returning a list of ParsedTable
        instances'''
        result = []
        lines = data.splitlines()
        start = 0
        while start < len(lines):
            sep_line = cls._find_separator_line(lines[start:])
            if sep_line:
                sep_index, colmetrics = sep_line
                t = ParsedTable(sep_index, colmetrics, lines[start:])
                result.append(t)
                start += t.sep_index + 1 + len(t.rows)
            else:
                break
        return result

    # Column metrics:
    ColMetric = namedtuple('ColMetric', ('offset', 'width'))
        
    def __init__(self, sep_index, colmetrics, lines):
        self.sep_index, self.colmetrics = sep_index, colmetrics

        # Parse column headings:
        header_index = self.sep_index - 1
        self.colnames = self._split_cells(lines[header_index])

        # Parse rows:
        self.rows = []
        for line in lines[self.sep_index + 1:]:
            if line == '':
                break
            self.rows.append(self._split_cells(line))

        self.rawdata = '\n'.join(lines[header_index:header_index+len(self.rows)+2])

    def __str__(self):
        return self.rawdata
            
    def get_cell(self, x, y):
        return self.rows[y][x]

    def find_col(self, colname):
        # Find the index of the column with the given name
        for x, col in enumerate(self.colnames):
            if colname == col:
                return x
        raise ColumnNotFound(colname, self)

    def find_row(self, kvs):
        # Find the first row matching the criteria, or raise RowNotFound
        criteria = Criteria(self, kvs)
        for row in self.rows:
            if criteria.is_matched_by(row):
                return row
        raise RowNotFound(criteria, self)

    def find_cell(self, kvs, attr2name):
        criteria = Criteria(self, kvs)
        row = self.find_row(kvs)
        return row[self.find_col(attr2name)]

    def _get_cell_value(self, cellstr):
        if cellstr == '':
            return None

        # Remove ',' separators from numbers, and treat as decimal:
        m = re.match('^([0-9,]+)$', cellstr) # [0-9]\,
        if m:
            return int(cellstr.replace(',', ''))

        # Hexadecimal values:
        m = re.match('^(0x[0-9a-f]+)$', cellstr)
        if m:
            return int(cellstr, 16)

        # Keep as a str:
        return cellstr

    def _split_cells(self, line):
        row = []
        for col in self.colmetrics:
            cellstr = line[col.offset: col.offset+col.width].lstrip()
            cellvalue = self._get_cell_value(cellstr)
            row.append(cellvalue)
        return tuple(row)

    @classmethod
    def _find_separator_line(cls, lines):
        # Look for the separator line
        # Return (index, tuple of ColMetric)
        for i, line in enumerate(lines):
            if line.startswith('-'):
                widths = [len(frag) for frag in line.split('  ')]
                coldata = []
                offset = 0
                for width in widths:
                    coldata.append(cls.ColMetric(offset=offset, width=width))
                    offset += width + 2
                return (i, tuple(coldata))
            

# Test data for table parsing (edited fragment of output during development):
test_table = '''
junk line

       Domain        Kind                 Detail  Count  Allocated size
-------------  ----------  ---------------------  -----  --------------
       python         str                         3,891         234,936
uncategorized                        98312 bytes      1          98,312
uncategorized                         1544 bytes     43          66,392
uncategorized                         6152 bytes     10          61,520
       python       tuple                         1,421          54,168
                                                             0xdeadbeef
                                           TOTAL  9,377         857,592

another junk line

another table

Chunk size  Num chunks  Allocated size
----------  ----------  --------------
        16         100           1,600
        24          50           1,200
    TOTALS         150           2,800

more junk
'''

class ParserTests(unittest.TestCase):
    def test_table_data(self):
        tables = ParsedTable.parse_lines(test_table)
        self.assertEquals(len(tables), 2)
        pt = tables[0]

        # Verify column names:
        self.assertEquals(pt.colnames, ('Domain', 'Kind', 'Detail', 'Count', 'Allocated size'))

        # Verify (x,y) lookup, and type conversions:
        self.assertEquals(pt.get_cell(0, 0), 'python')
        self.assertEquals(pt.get_cell(1, 3), None)
        self.assertEquals(pt.get_cell(4, 5), 0xdeadbeef)
        self.assertEquals(pt.get_cell(4, 6), 857592)

        # Verify searching by value:
        self.assertEquals(pt.find_col('Count'), 3)
        self.assertEquals(pt.find_row([('Allocated size', 54168),]),
                          ('python', 'tuple', None, 1421, 54168))
        self.assertEquals(pt.find_cell([('Kind', 'str'),], 'Count'), 3891)

        # Error-checking:
        self.assertRaises(ColumnNotFound,
                          pt.find_col, 'Ensure that a non-existant column raises an error')
        self.assertRaises(RowNotFound,
                          pt.find_row, [('Count', -1)])

        # Verify that "rawdata" contains the correct string data:
        self.assert_(pt.rawdata.startswith('       Domain'))
        self.assert_(pt.rawdata.endswith('857,592'))

        # Test the second table:
        pt = tables[1]
        self.assertEquals(pt.colnames, ('Chunk size', 'Num chunks', 'Allocated size'))
        self.assertEquals(pt.get_cell(2, 2), 2800)
        self.assert_(pt.rawdata.startswith('Chunk size'))
        self.assert_(pt.rawdata.endswith('2,800'))


    def test_multiple_tables(self):
        tables = ParsedTable.parse_lines(test_table * 5)
        self.assertEquals(len(tables), 10)

if __name__ == "__main__":
    unittest.main()
