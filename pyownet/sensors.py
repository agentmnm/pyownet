# sensors

#
# Copyright 2013, 2014 Stefano Miccoli
# 
# This python package is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

from __future__ import print_function

import types
import re

from pyownet import protocol

_STRUCT_DIR = '/structure/'
_TYPE_CODE = dict(i=int, u=int, f=float, l=str, a=str, b=bytes, y=bool, 
    d=str, t=float, g=float, p=float)
PAGE = re.compile(r'.+\.[0-9]+')


class metasensor(type):

    def __new__(mcs, name, bases, namespace):
        for key, val in namespace.iteritems():
            if isinstance(val, dict):
                namespace[key] = metasensor('subdir', bases, val)()
        return super(metasensor, mcs).__new__(mcs, name, bases, namespace)


class _sensor(object):

    def __str__(self):
        return "%s at %s" % (self.type, self.address)


class Properties(object):
    
    def __init__(self, record):

        if not isinstance(record, bytes):
            raise TypeError('record must be bytes')
        record = record.decode()
        flds = record.split(',')
        if len(flds) < 7:
            raise ValueError('invalid record')

        self.type = flds[0]
        self.isarr = int(flds[1])
        self.arrlen = int(flds[2])
        self.mode = flds[3]
        self.len = int(flds[4])
        self.pers = flds[5]

    def __str__(self):
        return 'Properties: %s, %2d, %2d, %s, %3d, %s' % (self.type, 
            self.isarr, self.arrlen, self.mode, self.len, self.pers, )

def _pathname_mangle(path):
    path = path.replace('-', '_')
    for suffix in ('.ALL', '/', ):
        if path.endswith(suffix):
            path = path[:-len(suffix)]
    return path


def _sens_namespace(proxy, entity, structure):

    def getter(path, name, prop):
        cast = _TYPE_CODE[prop.type]
        read = lambda: cast(proxy.read(path))
        read.__doc__ = "returns %s as %s" % (path, cast)
        # fixme: str(name) is because in python 2 unicode is distinct form str
        read.__name__ = str(name)
        return read

    def rbuild(path):
        namespace = dict()
        pre = len(path)
        for i in proxy.dir(path, slash=True):
            name = _pathname_mangle(i[pre:])
            if i.endswith('/'):
                namespace[name] = rbuild(i)
            else:
                base = i.split('/', 2)[-1]
                if PAGE.match(base):
                    continue
                prop = structure[base]
                assert isinstance(prop, Properties)
                if prop.mode not in ('ro', 'rw'):
                    continue
                if prop.pers == 'f':
                    namespace[name] = getter(i, name, prop)()
                else:
                    namespace[name] = staticmethod(getter(i, name, prop))
        return namespace

    assert entity.endswith('/')
    assert proxy.present(entity)
    namespace = rbuild(entity) 
    return namespace

class Root(object):

    def __init__(self, hostport):

        if ':' in hostport:
            host, port = hostport.split(':')
            self.proxy = protocol.OwnetProxy(host, port)
        else:
            host = hostport
            self.proxy = protocol.OwnetProxy(host)
        self._structure = dict()

    def __str__(self):
        return 'root at {0}'.format(self.proxy)

    def _walk(self, root):

        ents = [root]
        while ents:
            ent = ents.pop()
            if ent.endswith('/'):
                ents.extend(self.proxy.dir(ent, slash=True))
            else:
                yield ent, self.proxy.read(ent)

    def _getstructure(self, family):
        assert isinstance(family, basestring)
        if family not in self._structure:
            self._structure[family] = dict((i.split('/',3)[-1], Properties(j))
                    for i, j in self._walk(_STRUCT_DIR + family + '/'))
        return self._structure[family]

    def scan(self):
        return self.proxy.dir('/', slash=True)

    def getsensor(self, path):
        assert self.proxy.present(path)
        assert path.endswith('/')
        family = self.proxy.read(path + 'family').decode()
        structure = self._getstructure(family)
        ns = _sens_namespace(self.proxy, path, structure)
        return metasensor(ns['type'], (_sensor, object), ns)()


def _main():

    import sys

    def recprint(prefix, s):
        fprint = lambda s1, s2: print(prefix+'{0!s:.<14} {1!r}'.format(s1, s2))
        for att in dir(s):
            fatt = getattr(s, att, None)
            if isinstance(fatt, types.FunctionType):
                try:
                    fprint(att+'()', fatt(), )
                except protocol.OwnetError as exp:
                    fprint(att+'()', exp, )
            elif isinstance(fatt, str) and not fatt.startswith('__'):
                fprint(att, fatt)
            elif isinstance(fatt, _sensor):
                head = prefix+att+'/'
                print(head)
                recprint(' '*(len(head)-1) + prefix, fatt)

    try:
        hostport = sys.argv[1]
    except IndexError:
        hostport = 'localhost'
    root = Root(hostport)
    print('sensors on {0}'.format(root))
    for i in root.scan():
        print()
        s = root.getsensor(i)
        print(s)
        recprint('|-', s, )

if __name__ == '__main__':
    _main()
