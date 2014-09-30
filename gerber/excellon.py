#! /usr/bin/env python
# -*- coding: utf-8 -*-

# copyright 2014 Hamilton Kibbe <ham@hamiltonkib.be>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import re
from .utils import parse_gerber_value
from .cnc import CncFile, FileSettings


def read(filename):
    """ Read data from filename and return an ExcellonFile
    """
    return ExcellonParser().parse(filename)


class ExcellonFile(CncFile):
    """ A class representing a single excellon file

    The ExcellonFile class represents a single excellon file.

    Parameters
    ----------
    tools : list
        list of gerber file statements

    hits : list of tuples
        list of drill hits as (<Tool>, (x, y))
    settings : dict
        Dictionary of gerber file settings

    filename : string
        Filename of the source gerber file

    Attributes
    ----------
    units : string
        either 'inch' or 'metric'.

    """
    def __init__(self, tools, hits, settings, filename=None):
        super(ExcellonFile, self).__init__(settings, filename)
        self.tools = tools
        self.hits = hits

    def report(self):
        """ Print drill report
        """
        pass

    def render(self, filename, ctx):
        """ Generate image of file
        """
        for tool, pos in self.hits:
            ctx.drill(pos[0], pos[1], tool.diameter)
        ctx.dump(filename)


class ExcellonTool(object):
    """ Excellon Tool class

    Parameters
    ----------
    settings : FileSettings (dict-like)
        File-wide settings.

    kwargs : dict-like
        Tool settings from the excellon statement. Valid keys are:
            diameter : Tool diameter [expressed in file units]
            rpm : Tool RPM
            feed_rate : Z-axis tool feed rate
            retract_rate : Z-axis tool retraction rate
            max_hit_count : Number of hits allowed before a tool change
            depth_offset : Offset of tool depth from tip of tool.

    Attributes
    ----------
    number : integer
        Tool number from the excellon file

    diameter : float
        Tool diameter in file units

    rpm : float
        Tool RPM

    feed_rate : float
        Tool Z-axis feed rate.

    retract_rate : float
        Tool Z-axis retract rate

    depth_offset : float
        Offset of depth measurement from tip of tool

    max_hit_count : integer
        Maximum number of tool hits allowed before a tool change

    hit_count : integer
        Number of tool hits in excellon file.
    """

    @classmethod
    def from_line(cls, line, settings):
        """ Create a Tool from an excellon gile tool definition line.

        Parameters
        ----------
        line : string
            Tool definition line from an excellon file.

        settings : FileSettings (dict-like)
            Excellon file-wide settings

        Returns
        -------
        tool : Tool
            An ExcellonTool representing the tool defined in `line`
        """
        commands = re.split('([BCFHSTZ])', line)[1:]
        commands = [(command, value) for command, value in pairwise(commands)]
        args = {}
        format = settings['format']
        zero_suppression = settings['zero_suppression']
        for cmd, val in commands:
            if cmd == 'B':
                args['retract_rate'] = parse_gerber_value(val, format, zero_suppression)
            elif cmd == 'C':
                args['diameter'] = parse_gerber_value(val, format, zero_suppression)
            elif cmd == 'F':
                args['feed_rate'] = parse_gerber_value(val, format, zero_suppression)
            elif cmd == 'H':
                args['max_hit_count'] = parse_gerber_value(val, format, zero_suppression)
            elif cmd == 'S':
                args['rpm'] = 1000 * parse_gerber_value(val, format, zero_suppression)
            elif cmd == 'T':
                args['number'] = int(val)
            elif cmd == 'Z':
                args['depth_offset'] = parse_gerber_value(val, format, zero_suppression)
        return cls(settings, **args)

    def __init__(self, settings, **kwargs):
        self.number = kwargs.get('number')
        self.feed_rate = kwargs.get('feed_rate')
        self.retract_rate = kwargs.get('retract_rate')
        self.rpm = kwargs.get('rpm')
        self.diameter = kwargs.get('diameter')
        self.max_hit_count = kwargs.get('max_hit_count')
        self.depth_offset = kwargs.get('depth_offset')
        self.units = settings.get('units', 'inch')
        self.hit_count = 0

    def _hit(self):
        self.hit_count += 1

    def __repr__(self):
        unit = 'in.' if self.units == 'inch' else 'mm'
        return '<ExcellonTool %d: %0.3f%s dia.>' % (self.number, self.diameter, unit)


class ExcellonParser(object):
    """ Excellon File Parser
    """
    def __init__(self, ctx=None):
        self.ctx = ctx
        self.notation = 'absolute'
        self.units = 'inch'
        self.zero_suppression = 'trailing'
        self.format = (2, 5)
        self.state = 'INIT'
        self.tools = {}
        self.hits = []
        self.active_tool = None
        self.pos = [0., 0.]
        if ctx is not None:
            self.ctx.set_coord_format(zero_suppression='trailing',
                                      format=(2, 5), notation='absolute')

    def parse(self, filename):
        with open(filename, 'r') as f:
            for line in f:
                self._parse(line)
        return ExcellonFile(self.tools, self.hits, self._settings(), filename)

    def dump(self, filename):
        if self.ctx is not None:
            self.ctx.dump(filename)

    def _parse(self, line):
        if 'M48' in line:
            self.state = 'HEADER'

        if 'G00' in line:
            self.state = 'ROUT'

        if 'G05' in line:
            self.state = 'DRILL'

        elif line[0] == '%' and self.state == 'HEADER':
            self.state = 'DRILL'

        if 'INCH' in line or line.strip() == 'M72':
            self.units = 'inch'

        elif 'METRIC' in line or line.strip() == 'M71':
            self.units = 'metric'

        if 'LZ' in line:
            self.zeros = 'L'

        elif 'TZ' in line:
            self.zeros = 'T'

        if 'ICI' in line and 'ON' in line or line.strip() == 'G91':
            self.notation = 'incremental'

        if 'ICI' in line and 'OFF' in line or line.strip() == 'G90':
            self.notation = 'incremental'

        zs = self._settings()['zero_suppression']
        fmt = self._settings()['format']

        # tool definition
        if line[0] == 'T' and self.state == 'HEADER':
            tool = ExcellonTool.from_line(line, self._settings())
            self.tools[tool.number] = tool

        elif line[0] == 'T' and self.state != 'HEADER':
            self.active_tool = self.tools[int(line.strip().split('T')[1])]

        if line[0] in ['X', 'Y']:
            x = None
            y = None
            if line[0] == 'X':
                splitline = line.strip('X').split('Y')
                x = parse_gerber_value(splitline[0].strip(), fmt, zs)
                if len(splitline) == 2:
                    y = parse_gerber_value(splitline[1].strip(), fmt, zs)
            else:
                y = parse_gerber_value(line.strip(' Y'), fmt, zs)
            if self.notation == 'absolute':
                if x is not None:
                    self.pos[0] = x
                if y is not None:
                    self.pos[1] = y
            else:
                if x is not None:
                    self.pos[0] += x
                if y is not None:
                    self.pos[1] += y
            if self.state == 'DRILL':
                self.hits.append((self.active_tool, self.pos))
                self.active_tool._hit()
                if self.ctx is not None:
                    self.ctx.drill(self.pos[0], self.pos[1],
                                   self.active_tool.diameter)

    def _settings(self):
        return FileSettings(units=self.units, format=self.format,
                            zero_suppression=self.zero_suppression,
                            notation=self.notation)



def pairwise(iterator):
    itr = iter(iterator)
    while True:
        yield tuple([itr.next() for i in range(2)])

if __name__ == '__main__':
    p = parser()
    p.parse('examples/ncdrill.txt')