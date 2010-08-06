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

class Expression(object):
    def __eq__(self, other):
        if type(self) != type(other):
            return False

        return self.__dict__ == other.__dict__

    def iter_usage(self):
        from heap import iter_usage
        for u in iter_usage():
            if self._eval(u):
                yield u
    
    def _eval(self, ctx):
        raise NotImplementedError

class Comparison(Expression):
    def __init__(self, lhs, op, rhs):
        self.lhs = lhs
        self.op = op
        self.rhs = rhs

    def __repr__(self):
        return 'Comparison(%r, %r, %r)' % (self.lhs, self.op, self.rhs)

    def __eq__(self, other):
        return self.lhs == other.lhs and self.op == other.op and self.rhs == other.rhs

    def _eval(self, ctx):
        lhs = self.lhs._eval(ctx)
        rhs = self.rhs._eval(ctx)
        return getattr(lhs, self.op)(rhs)
        #intattrs = ('start', 'size')
        #if self.lhs in intattrs:
        #print 'foo'

class InfixBoolean(object):
    def __init__(self, a, b):
        self.a = a
        self.b = b
    def __eq__(self, other):
        return self.a == other.a and self.b == other.b
        
class And(InfixBoolean):
    def __repr__(self):
        return 'And(%r, %r)' % (self.a, self.b)

class Or(InfixBoolean):
    def __repr__(self):
        return 'Or(%r, %r)' % (self.a, self.b)

class Not(object):
    def __init__(self, a):
        self.a = a
    def __repr__(self):
        return 'Not(%r)' % (self.a, )

def p_expression_number(t):
    'expression : LITERAL_NUMBER'
    t[0] = t[1]

def p_expression_string(t):
    'expression : LITERAL_STRING'
    t[0] = t[1]

def p_comparison(t):
    'expression : expression COMPARISON expression'
    t[0] = Comparison(t[1], t[2], t[3])

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
    t[0] = t[1]
 
class ParserError(Exception):
    def __init__(self, input_, pos, value):
        self.input_ = input_
        self.pos = pos
        self.value = value
    
    def __str__(self):
        return ('Parse error at "%s":\n%s\n%s'
                % (self.value, self.input_, ' '*self.pos + '^'*len(self.value)))

def p_error(t):
    raise ParserError(t.lexer.lexdata, t.lexer.lexpos - len(t.value), t.value)


############################################################################
# Interface:
############################################################################

# Entry point:
def parse_query(s):
    #try:
    parser = yacc.yacc()
    return parser.parse(s)#, debug=1)
    #except ParserError, e:
    #    print 'foo', e

def test_lexer(s):
    lexer.input(s)
    while True:
        tok = lexer.token()
        if not tok: break
        print tok



