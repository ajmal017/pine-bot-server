# coding=utf-8

from inspect import getmembers, isfunction, ismethod

from . import builtin_function
from . import builtin_variable
from ..base import PineError

from .helper import Series, BuiltinSeries, NaN

class VM (object):

    def __init__ (self, market):
        self.prepare_function_table()
        self.prepare_variable_tables()
        self.market = market
        self.title = 'No Title'

    def _load_builtins (self, mod, mod_sfx, dest):
        for name, func in getmembers(mod, isfunction):
            if not func.__module__.endswith(mod_sfx):
                continue
            if name.startswith('_'):
                continue
            name = name.replace('__', '.')
            dest[name] = func

    # TODO separate bultin table from user-defined one.
    def prepare_function_table (self):
        self.function_table = {}
        self._load_builtins(builtin_function, '.builtin_function', self.function_table)

    def register_function (self, name, args, node):
        self.function_table[name] = (args, node)

    def prepare_variable_tables (self):
        self.variable_tables = []
        # global scope
        tbl = {}
        self.variable_tables.append(tbl)
        self._load_builtins(builtin_variable, '.builtin_variable', tbl)

    def define_variable (self, name, value):
        self.variable_tables[-1][name] = value

    def assign_variable (self, name, value):
        for t in reversed(self.variable_tables):
            if name in t:
                v = t[name]
                if isinstance(v, Series):
                    compat = isinstance(value, Series)
                else:
                    compat = (type(v) == type(value))
                if not compat:
                    raise PineError('invalid type to assign: {0}: {1} for {2}'.format(name, value, t[name]))
                t[name] = value
                return value
        raise PineError('variable not found to assign: {}'.format(name))

    def lookup_variable (self, name):
        for t in reversed(self.variable_tables):
            if name in t:
                v = t[name]
                if isfunction(v):
                    try:
                        return v(self)
                    except NotImplementedError as e:
                        raise PineError('variable is not implemented: {}'.format(name)) from e
                return v
        raise PineError("variable not found: {}".format(name))

    def push_scope (self):
        self.variable_tables.append({})
        
    def pop_scope (self):
        self.variable_tables.pop(-1)

    def func_call (self, fname, args, kwargs):
        func = self.function_table.get(fname, None)
        if func is None:
            raise PineError('function is not found: {}'.format(fname))
        if isfunction(func) or ismethod(func):
            try:
                return func(self, args, kwargs)
            except builtin_function.PineArgumentError as e:
                raise PineError('{0}: {1}'.format(e, fname)) from e
            except NotImplementedError as e:
                raise PineError('function is not implemented: {}'.format(fname)) from e
        else:
            arg_ids, node = func
            try:
                self.push_scope()
                self._set_func_arguments(arg_ids, args, kwargs)
                return node.eval(self)
            finally:
                self.pop_scope()

    def _set_func_arguments (self, names, args, kwargs):
        if args:
            for n, a in zip(names, args):
                self.define_variable(n, a)
        if kwargs:
            for k, a in kwargs.items():
                self.define_variable(k, a)

        for n in names:
            if n not in self.variable_tables[-1]:
                raise PineError("missing argument: {}".format(n))

    def eval_node (self, node):
        self.push_scope()
        try:
            node.eval(self)
        finally:
            self.pop_scope()



class InputScanner (VM):

    def __init__ (self, market):
        super().__init__(market)
        self.function_table['input'] = self.input
        self.inputs = []

    def eval_node (self, node):
        super().eval_node(node)

    def input (self, vm, args, kwargs):
        defval, title, typ,\
        minval, maxval, confirm, step, options = builtin_function._parse_input_args(args, kwargs)
    
        defval_ = defval
        if typ is None:
            t = type(defval)
            if t == bool:
                typ = 'bool'
            elif t == int:
                typ = 'integer'
            elif t == float:
                typ = 'float'
            elif isinstance(defval, BuiltinSeries):
                typ = 'source'
                defval_ = defval.varname
            else:
                typ = 'string'
                # symbol, resolution, session

        if not title:
            title = "input{}".format(len(self.inputs) + 1)

        self.inputs.append({
            'defval': defval_,
            'title': title,
            'type': typ,
            'minval': minval,
            'maxval': maxval,
            'options': options,
        })
        return defval


class RenderVM (VM):

    def __init__ (self, market, inputs):
        super().__init__(market)
        self.inputs = inputs
        self.function_table['input'] = self.input
        self.function_table['plot'] = self.plot
        self.function_table['hline'] = self.hline
        self.function_table['fill'] = self.fill
        self.plots = []
        self.input_idx = 0

    def input (self, vm, args, kwargs):
        defval, title, typ,\
        minval, maxval, confirm, step, options = builtin_function._parse_input_args(args, kwargs)

        self.input_idx += 1
        if not title:
            title = "input{}".format(self.input_idx)

        val = self.inputs[title]
        # bool, integer, float, string, symbol, resolution, session, source
        if not typ:
            t = type(defval)
            if t == bool:
                typ = 'bool'
            elif t == int:
                typ = 'integer'
            elif t == float:
                typ = 'float'
            elif isinstance(defval, BuiltinSeries):
                typ = 'source'

        if typ == 'bool':
            val = bool(val)
        elif typ == 'integer':
            val = int(val)
        elif typ == 'float':
            val = float(val)
        elif typ == 'source':
            val = self.lookup_variable(val)

        return val

    def plot (self, vm, args, kwargs):
        series, title, color, linewidth, style,\
         trackprice, transp, histbase,\
         offset, join, editable, show_last = builtin_function._expand_args(args, kwargs, (
            ('series', Series, True),
            ('title', str, True),
            ('color', None, False),
            ('linewidth', int, False),
            ('style', int, False),
            ('trackprice', bool, False),
            ('transp', int, False),
            ('histbase', float, False),
            ('offset', int, False),
            ('join', bool, False),
            ('editable', bool, False),
            ('show_last', int, False),
        ))

        plot = {'title': title, 'series': series}

        if style:
            if style == builtin_variable.STYLE_LINE:
                typ = 'line'
            elif style == builtin_variable.STYLE_STEPLINE:
                typ = 'line' 
            elif style == builtin_variable.STYLE_HISTOGRAM:
                typ = 'bar' 
            elif style == builtin_variable.STYLE_CROSS:
                typ = 'marker'
                plot['mark'] = '+'
            elif style == builtin_variable.STYLE_AREA:
                typ = 'band'
            elif style == builtin_variable.STYLE_COLUMNS:
                typ = 'bar'
            elif style == builtin_variable.STYLE_CIRCLES:
                typ = 'marker'
                plot['mark'] = 'o'
            else:
                typ = 'line'
            plot['type'] = typ

        if color is not None:
            if isinstance(color, Series):
                color = color[-1]
            plot['color'] = color
        if linewidth:
            plot['width'] = linewidth
        if transp:
            plot['alpha'] = transp * 0.01

        self.plots.append(plot)
        return plot

    def hline (self, vm, args, kwargs):
        price, title,\
         color, linestyle, linewidth, editable = builtin_function._expand_args(args, kwargs, (
            ('price', float, True),
            ('title', str, False),
            ('color', str, False),
            ('linestyle', int, False),
            ('linewidth', int, False),
            ('editable', bool, False),
        ))

        plot = {'title': title, 'series': price, 'type': 'hline'}
        if color:
            plot['color'] = color
        if linewidth:
            plot['width'] = linewidth
            
        self.plots.append(plot)
        return plot

    def fill (self, vm, args, kwargs):
        s1, s2,\
         color, transp, title, editable, _ = builtin_function._expand_args(args, kwargs, (
            ('series1', dict, True),
            ('series2', dict, True),
            ('color', str, False),
            ('transp', int, False),
            ('title', str, False),
            ('editable', bool, False),
            ('show_last', bool, False),
        ))

        plot = {'title': title, 'series': s1['series'], 'series2': s2['series'], 'type': 'fill'}
        
        if color is not None:
            if isinstance(color, Series):
                color = color[-1]
            plot['color'] = color
        if transp:
            plot['alpha'] = transp * 0.01

        self.plots.append(plot)
        return plot
