# Copyright (C) 2010  David Hugh Malcolm
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


# Query language for the heap

# Uses "ply", so we'll need python-ply on Fedora

# Split into tokenizer, then grammar, then external interface

############################################################################
# Tokenizer:
############################################################################
import ply.lex as lex

reserved = ['AND', 'OR', 'NOT']
tokens = [
    'ID','LITERAL_NUMBER', 'LITERAL_STRING',
    'LPAREN','RPAREN',
    'COMPARISON'
    ] + reserved
        
t_LPAREN  = r'\('
t_RPAREN  = r'\)'

def t_ID(t):
    r'[a-zA-Z_][a-zA-Z_0-9]*'
    # Check for reserved words (case insensitive):
    if t.value.upper() in reserved:
        t.type = t.value.upper()
    else:
        t.type = 'ID'
    return t

def t_COMPARISON(t):
    r'<=|<|==|=|!=|>=|>'
    return t

def t_LITERAL_NUMBER(t):
    r'(0x[0-9a-fA-F]+|\d+)'
    try:
        if t.value.startswith('0x'):
            t.value = long(t.value, 16)
        else:
            t.value = long(t.value)
    except ValueError:
        raise ParserError(t.value)
    return t

def t_LITERAL_STRING(t):
    r'"([^"]*)"'
    # Drop the quotes:
    t.value = t.value[1:-1]
    return t

# Ignored characters
t_ignore = " \t"

def t_newline(t):
    r'\n+'
    t.lexer.lineno += t.value.count("\n")
    
def t_error(t):
    print "Illegal character '%s'" % t.value[0]
    t.lexer.skip(1)

lexer = lex.lex()


############################################################################
# Grammar:
############################################################################
import ply.yacc as yacc

precedence = (
    ('left', 'AND', 'OR'),
    ('left', 'NOT'),
    ('left', 'COMPARISON'),
)

from heap.query import Constant, And, Or, Not, GetAttr, \
    Comparison__le__, Comparison__lt__, Comparison__eq__, \
    Comparison__ne__, Comparison__ge__, Comparison__gt__


def p_expression_number(t):
    'expression : LITERAL_NUMBER'
    t[0] = Constant(t[1])

def p_expression_string(t):
    'expression : LITERAL_STRING'
    t[0] = Constant(t[1])

def p_comparison(t):
    'expression : expression COMPARISON expression'
    classes = { '<=' : Comparison__le__,
                '<'  : Comparison__lt__,
                '==' : Comparison__eq__,
                '='  : Comparison__eq__,
                '!=' : Comparison__ne__,
                '>=' : Comparison__ge__,
                '>'  : Comparison__gt__ }
    cls = classes[t[2]]

    t[0] = cls(t[1], t[3])

def p_and(t):
    'expression : expression AND expression'
    t[0] = And(t[1], t[3])

def p_or(t):
    'expression : expression OR expression'
    t[0] = Or(t[1], t[3])

def p_not(t):
    'expression : NOT expression'
    t[0] = Not(t[2])

def p_expression_group(t):
    'expression : LPAREN expression RPAREN'
    t[0] = t[2]

def p_expression_name(t):
    'expression : ID'
    attrname = t[1]
    attrnames = ('domain', 'kind', 'detail', 'addr', 'start', 'size')
    if attrname not in attrnames:
        raise ParserError.from_production(t, attrname,
                                          ('Unknown attribute "%s" (supported are %s)'
                                           % (attrname, ','.join(attrnames))))
    t[0] = GetAttr(attrname)
 
class ParserError(Exception):
    @classmethod
    def from_production(cls, p, val, msg):
        return ParserError(p.lexer.lexdata,
                           p.lexer.lexpos - len(val),
                           val,
                           msg)

    @classmethod
    def from_token(cls, t, msg="Parse error"):
        return ParserError(t.lexer.lexdata,
                           t.lexer.lexpos - len(t.value),
                           t.value,
                           msg)

    def __init__(self, input_, pos, value, msg):
        self.input_ = input_
        self.pos = pos
        self.value = value
        self.msg = msg
    
    def __str__(self):
        return ('%s at "%s":\n%s\n%s'
                % (self.msg, self.value,
                   self.input_,
                   ' '*self.pos + '^'*len(self.value)))

def p_error(t):
    raise ParserError.from_token(t)


############################################################################
# Interface:
############################################################################

# Entry point:
def parse_query(s):
    #try:
    parser = yacc.yacc(debug=0, write_tables=0)
    return parser.parse(s)#, debug=1)
    #except ParserError, e:
    #    print 'foo', e

def test_lexer(s):
    lexer.input(s)
    while True:
        tok = lexer.token()
        if not tok: break
        print tok



