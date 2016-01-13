"""owserver protocol implementation

This module is a pure python, low level implementation of the owserver
protocol.

Interaction with an owserver takes place via a proxy object whose methods
correspond to owserver messages. Proxy objects are created by factory
function 'proxy'.

>>> owproxy = proxy(host="owserver.example.com", port=4304)
>>> owproxy.dir()
[u'/28.000028D70000/', u'/26.000026D90100/']
>>> owproxy.read('/28.000028D70000/temperature')
'           4'
>>> owproxy.write('/28.000028D70000/alias', 'sensA')
>>> owproxy.write('/26.000026D90100/alias', 'sensB')
>>> owproxy.dir()
[u'/sensA/', u'/sensB/']
>>> owproxy.read('/sensA/temperature')
'           4'
>>> owproxy.read('/sensB/temperature')
'         3.9'

"""

#
# Copyright 2013-2016 Stefano Miccoli
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

import struct
import socket

from . import Error as _Error

import time

#
# owserver protocol related constants
#

# for message type classification see
# http://owfs.org/index.php?page=owserver-message-types
# and 'enum msg_classification' from module/owlib/src/include/ow_message.h

MSG_ERROR = 0
MSG_NOP = 1
MSG_READ = 2
MSG_WRITE = 3
MSG_DIR = 4
MSG_PRESENCE = 6
MSG_DIRALL = 7
MSG_GET = 8
MSG_DIRALLSLASH = 9
MSG_GETSLASH = 10

# for owserver flag word definition see
# http://owfs.org/index.php?page=owserver-flag-word
# and module/owlib/src/include/ow_parsedname.h

FLG_BUS_RET = 0x00000002
FLG_PERSISTENCE = 0x00000004
FLG_ALIAS = 0x00000008
FLG_SAFEMODE = 0x00000010
FLG_UNCACHED = 0x00000020
FLG_OWNET = 0x00000100

# see also 'enum temp_type' in module/owlib/src/include/ow_temperature.h
FLG_TEMP_C = 0x00000000
FLG_TEMP_F = 0x00010000
FLG_TEMP_K = 0x00020000
FLG_TEMP_R = 0x00030000
MSK_TEMPSCALE = 0x00030000

# see also 'enum pressure_type' in module/owlib/src/include/ow_pressure.h
FLG_PRESS_MBAR = 0x00000000
FLG_PRESS_ATM = 0x00040000
FLG_PRESS_MMHG = 0x00080000
FLG_PRESS_INHG = 0x000C0000
FLG_PRESS_PSI = 0x00100000
FLG_PRESS_PA = 0x00140000
MSK_PRESSURESCALE = 0x001C0000

# see also 'enum deviceformat' in module/owlib/src/include/ow.h
FLG_FORMAT_FDI = 0x00000000    # /10.67C6697351FF
FLG_FORMAT_FI = 0x01000000     # /1067C6697351FF
FLG_FORMAT_FDIDC = 0x02000000  # /10.67C6697351FF.8D
FLG_FORMAT_FDIC = 0x03000000   # /10.67C6697351FF8D
FLG_FORMAT_FIDC = 0x04000000   # /1067C6697351FF.8D
FLG_FORMAT_FIC = 0x05000000    # /1067C6697351FF8D
MSK_DEVFORMAT = 0xFF000000

#
# useful owfs paths
#

PTH_ERRCODES = '/settings/return_codes/text.ALL'
PTH_VERSION = '/system/configuration/version'
PTH_PID = '/system/process/pid'

#
# implementation specific constants
#

# do not attempt to read messages bigger than this (bytes)
MAX_PAYLOAD = 65536

# socket timeout (s)
_SCK_TIMEOUT = 2.0

# socket and errno module constants
_SOL_SOCKET = socket.SOL_SOCKET
_SO_KEEPALIVE = socket.SO_KEEPALIVE
if __debug__:
    import errno
    _ENOTCONN = errno.ENOTCONN


#
# code/decode functions
#

def str2bytez(s):
    """Transform string to zero-terminated bytes."""

    if not isinstance(s, basestring):
        raise TypeError()
    return s.encode('ascii') + b'\x00'


def bytes2str(b):
    """Transform bytes to string."""

    if not isinstance(b, (bytes, bytearray, )):
        raise TypeError()
    return b.decode('ascii')


#
# exceptions
#

class Error(_Error):
    """Base class for all module errors."""


class ConnError(Error, IOError):
    """Raised if no valid connection can be established with owserver."""


class ProtocolError(Error):
    """Raised if no valid server response received."""


class ComTimeoutError(Error):
    """Raised if response of server takes longer than a given timeout."""


class MalformedHeader(ProtocolError):
    """Raised for header parsing errors."""

    def __init__(self, msg, header):
        self.msg = msg
        self.header = header

    def __str__(self):
        return "{0.msg}, got {1!r} decoded as {0.header!r}".format(
            self, str(self.header))


class ShortRead(ProtocolError):
    """Raised if not enough date received."""


class ShortWrite(ProtocolError):
    """Raised if unable to write all data."""


class OwnetError(Error, EnvironmentError):
    """Raised when owserver returns error code"""


#
# supporting types (internal)
#

class _errtuple(tuple):
    """tuple subtype for "error number" -> "error message" mapping

    if error number is not defined returns a standard message
    """

    _message = ''

    def __getitem__(self, i):
        try:
            return super(_errtuple, self).__getitem__(i)
        except IndexError:
            return self._message


#
# classes for message headers (internal)
#

class _addfieldprops(type):
    """metaclass for adding properties"""

    @staticmethod
    def _getter(i):
        return lambda x: x._vals[i]

    def __new__(mcs, name, bases, namespace):
        if '_format' in namespace:
            assert '_fields' in namespace
            assert '_defaults' in namespace
            assert len(namespace['_defaults']) == len(namespace['_fields'])

            namespace['_struct'] = struct.Struct(namespace['_format'])
            namespace['header_size'] = namespace['_struct'].size
            for i, key in enumerate(namespace['_fields']):
                assert key not in namespace
                namespace[key] = property(mcs._getter(i))
            if __debug__:
                try:
                    namespace['_struct'].pack(*namespace['_defaults'])
                except struct.error as err:
                    raise AssertionError('Unable to pack _defaults: %s' % err)

        return super(_addfieldprops, mcs).__new__(mcs, name, bases, namespace)


class _Header(bytes):
    """abstract header class, obtained as a 'bytes' subclass

    should not be instantiated directly
    """

    __metaclass__ = _addfieldprops

    @classmethod
    def _parse(cls, *args, **kwargs):
        if args:
            msg = args[0]
            # FIXME check for args type and semantics
            assert len(args) == 1
            assert not kwargs
            assert isinstance(msg, (bytes, bytearray, ))
            assert len(msg) == cls.header_size
            #
            vals = cls._struct.unpack(msg)
        else:
            vals = tuple(map(kwargs.pop, cls._fields, cls._defaults))
            if kwargs:
                raise TypeError("constructor got unexpected keyword argument"
                                " '%s'" % kwargs.popitem()[0])
            msg = cls._struct.pack(*vals)
        assert isinstance(msg, (bytes, bytearray, ))
        assert isinstance(vals, tuple)
        return msg, vals

    def __repr__(self):
        repr = self.__class__.__name__ + '('
        repr += ', '.join('%s=%s' % x for x in zip(self._fields, self._vals))
        repr += ')'
        return repr

    def __new__(cls, *args, **kwargs):
        # if cls is _Header:
        #     raise TypeError("_Header class may not be instantiated")
        msg, vals = cls._parse(*args, **kwargs)
        self = super(_Header, cls).__new__(cls, msg)
        self._vals = vals
        return self


class _ToServerHeader(_Header):
    """client to server request header"""

    _format = '>iiiiii'
    _fields = ('version', 'payload', 'type', 'flags', 'size', 'offset')
    _defaults = (0, 0, MSG_NOP, FLG_OWNET, 0, 0)


class _FromServerHeader(_Header):
    """server to client reply header"""

    _format = '>iiiiii'
    _fields = ('version', 'payload', 'ret', 'flags', 'size', 'offset')
    _defaults = (0, 0, 0, FLG_OWNET, 0, 0)


#
# connection object (internal)
#

class _OwnetConnection(object):
    """This class encapsulates a connection to an owserver."""

    def __init__(self, sockaddr, family=socket.AF_INET, verbose=False):
        """establish a connection with server at sockaddr"""

        self.verbose = verbose

        self.socket = socket.socket(family, socket.SOCK_STREAM)
        self.socket.settimeout(_SCK_TIMEOUT)
        # FIXME: is _SO_KEEPALIVE really useful?
        self.socket.setsockopt(_SOL_SOCKET, _SO_KEEPALIVE, 1)
        self.socket.connect(sockaddr)

        if self.verbose:
            print(self.socket.getsockname(), '->', self.socket.getpeername())

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()

    def __str__(self):
        return "_OwnetConnection {0} -> {1}".format(self.socket.getsockname(),
                                                    self.socket.getpeername())

    def shutdown(self):
        """shutdown connection"""

        if self.verbose:
            print(self.socket.getsockname(), 'xx', self.socket.getpeername())

        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except IOError as err:
            assert err.errno is _ENOTCONN, "unexpected IOError: %s" % err
            pass
        self.socket.close()

    def req(self, msgtype, payload, flags, size=0, offset=0, timeout=0):
        """send message to server and return response"""

        if timeout < 0:
            raise ValueError("timeout cannot be negative!")
        
        tohead = _ToServerHeader(payload=len(payload), type=msgtype,
                                 flags=flags, size=size, offset=offset)

        tstartcom = time.time() # set timer when communication begins
        self._send_msg(tohead, payload)
        
        while True:
            fromhead, data = self._read_msg()

            if fromhead.payload >= 0 :  # Question for Stefano: is it greater and equal? Can payload be 0 and be valid unless the message was MSG_NOP?
                # we recieved a valid answer and return the result
                return fromhead.ret, fromhead.flags, data
            
            if msgtype == MSG_NOP:    # if msg was a Ping # Remark for Stefano: if the above is greater and equal 0, this will never be True, because we alredy returned above
                # then we don't expect the payload to be greater than 0 and return
                return fromhead.ret, fromhead.flags, data

            # we did not exit the loop because:
            # payload is negative
            # Server said PING to keep connection alive during lenghty op
            if timeout > 0: # if a timeout was set by the user
                tcom = time.time() - tstartcom
                if tcom > timeout:
                    raise ComTimeoutError("Communication with owserver aborted after %2.1fs, timeout of %2.1fs exceeded" % (tcom, timeout))


    def _send_msg(self, header, payload):
        """send message to server"""

        if self.verbose:
            print('->', repr(header))
            print('..', repr(payload))
        assert header.payload == len(payload)
        sent = self.socket.send(header + payload)
        if sent < len(header + payload):
            raise ShortWrite()
        assert sent == len(header + payload), sent

    #
    # NOTE:
    # '_read_socket(self, nbytes)' was implemented as
    # 'return self.socket.recv(nbytes, socket.MSG_WAITALL)'
    # but socket.MSG_WAITALL proved not reliable
    #

    def _read_socket(self, nbytes):
        """read nbytes bytes from self.socket"""

        buf = self.socket.recv(nbytes)
        while len(buf) < nbytes:
            tmp = self.socket.recv(nbytes - len(buf))
            if len(tmp) == 0:
                if self.verbose and buf:
                    print('ee', repr(buf))
                raise ShortRead("short read: read %d bytes instead of %d"
                                % (len(buf), nbytes, ))
            buf += tmp
        assert len(buf) == nbytes, (buf, len(buf), nbytes)
        return buf

    def _read_msg(self):
        """read message from server"""

        header = _FromServerHeader(self._read_socket(_FromServerHeader
                                                     .header_size))
        if self.verbose:
            print('<-', repr(header))

        # error conditions
        if header.version != 0:
            raise MalformedHeader('bad version', header)
        if header.payload > MAX_PAYLOAD:
            raise MalformedHeader('huge payload, unwilling to read', header)

        if header.payload > 0:
            payload = self._read_socket(header.payload)
            if self.verbose:
                print('..', repr(payload))
            assert header.size <= header.payload
            payload = payload[:header.size]
        else:
            payload = bytes()
        return header, payload


#
# proxy objects
#

class _Proxy(object):
    """Proxy object with methods to query an owserver,
    socket connection is non persistent, stateless, thread-safe
    """

    def __init__(self, family, address, flags=0,
                 verbose=False, errmess=_errtuple(), ):
        if flags & FLG_PERSISTENCE:
            raise ValueError('cannot set FLG_PERSISTENCE')

        # save init args
        self._family, self._sockaddr = family, address
        self.flags = flags
        self.verbose = verbose
        self.errmess = errmess

    def __str__(self):
        return "owserver at %s" % (self._sockaddr, )

    def _init_errcodes(self):
        # fetch errcodes array from owserver
        try:
            self.errmess = _errtuple(
                m for m in bytes2str(self.read(PTH_ERRCODES)).split(','))
        except OwnetError:
            # failed, leave the default empty errcodes
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def sendmess(self, msgtype, payload, flags=0, size=0, offset=0, timeout=0):
        """ retcode, data = sendmess(msgtype, payload)
        send generic message and returns retcode, data
        """

        flags |= self.flags
        assert not (flags & FLG_PERSISTENCE)

        try:
            with _OwnetConnection(
                    self._sockaddr, self._family, self.verbose) as conn:
                ret, _, data = conn.req(msgtype, payload, flags, size, offset, timeout)
        except IOError as err:
            raise ConnError(*err.args)

        return ret, data

    def ping(self, timeout=0):
        # remark for Stefano, I dont think its needed, but this way it is consequent
        """sends a NOP packet and waits response; returns None"""

        ret, data = self.sendmess(MSG_NOP, bytes(), timeout=0)
        if (ret, data) != (0, bytes()):
            raise OwnetError(-ret, self.errmess[-ret])

    def present(self, path, timeout=0):
        """returns True if there is an entity at path"""

        ret, data = self.sendmess(MSG_PRESENCE, str2bytez(path), timeout=0)
        assert ret <= 0 and len(data) == 0
        if ret < 0:
            return False
        else:
            return True

    def dir(self, path='/', slash=True, bus=False, timeout=0):
        """list entities at path"""

        if slash:
            msg = MSG_DIRALLSLASH
        else:
            msg = MSG_DIRALL
        if bus:
            flags = self.flags | FLG_BUS_RET
        else:
            flags = self.flags & ~FLG_BUS_RET

        ret, data = self.sendmess(msg, str2bytez(path), flags, timeout=timeout)
        if ret < 0:
            raise OwnetError(-ret, self.errmess[-ret], path)
        if data:
            return bytes2str(data).split(',')
        else:
            return []

    def read(self, path, timeout=0, size=MAX_PAYLOAD, offset=0):
        # remark for Stefano: I put timeout as second parameter, so its easy to use as second param without having to name it
        """read data at path"""

        if size > MAX_PAYLOAD:
            raise ValueError("size cannot exceed %d" % MAX_PAYLOAD)
        
        ret, data = self.sendmess(MSG_READ, str2bytez(path),
                                  size=size, offset=offset, timeout=timeout)
        if ret < 0:
            raise OwnetError(-ret, self.errmess[-ret], path)
        return data

    def write(self, path, data, timeout=0, offset=0):
        """write data at path

        path is a string, data binary; it is responsability of the caller
        ensure proper encoding.
        """

        # fixme: check of path type delayed to str2bytez
        if not isinstance(data, (bytes, bytearray, )):
            raise TypeError("'data' argument must be binary")
        
        ret, rdata = self.sendmess(MSG_WRITE, str2bytez(path)+data,
                                   size=len(data), offset=offset, timeout=timeout)
        assert len(rdata) == 0
        if ret < 0:
            raise OwnetError(-ret, self.errmess[-ret], path)


class _PersistentProxy(_Proxy):
    """Proxy object with methods to query an owserver,
    socket connection is persistent, statefull, not thread-safe
    """

    def __init__(self, family, address,
                 flags=0, verbose=False, errmess=_errtuple(), ):
        super(_PersistentProxy, self).__init__(
            family, address, flags, verbose, errmess)

        self.conn = None
        self.flags |= FLG_PERSISTENCE

    def __enter__(self):
        if not self.conn:
            self._open_connection()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_connection()

    def __del__(self):
        self.close_connection()

    def _open_connection(self):
        assert self.conn is None
        try:
            self.conn = _OwnetConnection(self._sockaddr,
                                         self._family,
                                         self.verbose)
        except IOError as err:
            raise ConnError(*err.args)

    def close_connection(self):
        if self.conn:
            self.conn.shutdown()
            self.conn = None
        else:
            assert self.conn is None

    def sendmess(self, msgtype, payload, flags=0, size=0, offset=0, timeout=0):
        """
        retcode, data = sendmess(msgtype, payload)
        send generic message and returns retcode, data
        """

        # ensure that there is an open connection
        if not self.conn:
            self._open_connection()
        assert self.conn is not None

        flags |= self.flags
        assert (flags & FLG_PERSISTENCE)
        try:
            ret, rflags, data = self.conn.req(
                msgtype, payload, flags, size, offset, timeout)
        except IOError as err:
            raise ConnError(*err.args)
        # persistence not granted
        if not (rflags & FLG_PERSISTENCE):
            self.close_connection()

        return ret, data


#
# factory functions
#

def proxy(host='localhost', port=4304, flags=0, persistent=False,
          verbose=False, ):
    """factory function that returns a proxy object for an owserver at
    host, port.
    """

    # resolve host name/port
    try:
        gai = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    except socket.gaierror as err:
        raise ConnError(*err.args)

    # gai is a list of tuples, search for the first working one
    lasterr = None
    for (family, _, _, _, sockaddr) in gai:
        try:
            owp = _PersistentProxy(family, sockaddr, flags, verbose)
            owp.__enter__()
        except ConnError as err:
            # not working, go over to next sockaddr
            lasterr = err
        else:
            # ok, this is working, stop searching
            break
    else:
        # no working (sockaddr, family) found: reraise last exception
        assert isinstance(lasterr, ConnError)
        raise lasterr

    with owp:
        try:
            # fixme: should this be only optional?
            owp._init_errcodes()
        except ConnError as err:
            raise ProtocolError('Error while connecting to owserver: {}'
                                .format(err))
        except ProtocolError as err:
            # pass ProtocolError unchanged
            raise err

    if not persistent:
        owp = clone(owp, persistent=False)

    return owp


def clone(proxy, persistent=True):
    """factory function for cloning a proxy object"""

    if not isinstance(proxy, _Proxy):
        raise TypeError('argument is not a Proxy object')

    if persistent:
        pclass = _PersistentProxy
    else:
        pclass = _Proxy

    return pclass(proxy._family, proxy._sockaddr,
                  proxy.flags & ~FLG_PERSISTENCE, proxy.verbose, proxy.errmess)
