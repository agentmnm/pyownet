"""this module is a first try to implement the ownet protocol"""

import struct
import socket

# see msg_classification from ow_message.h
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

# see http://owfs.org/index.php?page=owserver-flag-word
# and ow_parsedname.h
FLG_BUS_RET =     0x00000002
FLG_PERSISTENCE = 0x00000004
FLG_ALIAS =       0x00000008
FLG_SAFEMODE =    0x00000010
FLG_UNCACHED =    0x00000020
FLG_OWNET =       0x00000100

# look for 
# 'enum temp_type' in ow_temperature.h
# 'enum pressure_type' in ow_pressure.h
# 'enum deviceformat' in ow.h
MSK_TEMPSCALE =     0x00030000
MSK_PRESSURESCALE = 0x001C0000
MSK_DEVFORMAT =     0xFF000000

FLG_TEMP_C =        0x00000000
FLG_TEMP_F =        0x00010000
FLG_TEMP_K =        0x00020000
FLG_TEMP_R =        0x00030000

FLG_PRESS_MBAR =    0x00000000
FLG_PRESS_ATM =     0x00040000
FLG_PRESS_MMHG =    0x00080000
FLG_PRESS_INHG =    0x000C0000
FLG_PRESS_PSI =     0x00100000
FLG_PRESS_PA =      0x00140000

FLG_FORMAT_FDI =    0x00000000 #  /10.67C6697351FF
FLG_FORMAT_FI =     0x01000000 #  /1067C6697351FF
FLG_FORMAT_FDIDC =  0x02000000 #  /10.67C6697351FF.8D
FLG_FORMAT_FDIC  =  0x03000000 #  /10.67C6697351FF8D
FLG_FORMAT_FIDC =   0x04000000 #  /1067C6697351FF.8D
FLG_FORMAT_FIC =    0x05000000 #  /1067C6697351FF8D

# internal constants

# socket buffer
_SCK_BUFSIZ = 1024
_SCK_TIMEOUT = 1.0
# do not attempt to read messages bigger than this
_MAX_PAYLOAD = _SCK_BUFSIZ


#
# exceptions
# TODO: organize a better hierachy
#

class Error(Exception):
    """Base class for all module errors"""
    pass


class ConnError(Error, IOError):
    """Connection failed"""
    pass


class ShortRead(Error):
    pass


class ShortWrite(Error):
    pass


class ProtocolError(Error):
    pass


class OwnetError(Error, EnvironmentError):
    pass


#
# classes
#

class _addfieldprops(type):
    """metaclass for adding properties"""

    @staticmethod
    def _getter(i):
        return lambda x: x._vals[i]

    def __new__(mcs, name, bases, namespace):
        #TODO: check for name space clashes, sanity checks
        for i, j in enumerate(namespace.get('_fields', (), )):
            namespace[j] = property(mcs._getter(i))
        assert super(_addfieldprops, mcs).__new__ is type.__new__
        return super(_addfieldprops, mcs).__new__(mcs, name, bases, namespace)

    #def __call__(cls, *args, **kwargs):
    #   print cls._fields
    #   print args, kwargs
    #   return super(_addfieldprops, cls).__call__(*args, **kwargs)


class _HeaderT(object):
    """template class for ownet protocol headers"""

    __metaclass__ = _addfieldprops

    _format = struct.Struct(">iiiiii")
    hsize = _format.size

    # TODO: find a way to not allow instatiating _Header() directly
    _fields = ()
    _defaults = ()

    @classmethod
    def _parse(cls, *args, **kwargs):
        if args:
            msg = args[0]
            # FIXME check for args type and semantics
            assert len(args)==1
            assert not kwargs
            assert isinstance(msg, bytes)
            assert len(msg) == cls.hsize
            #
            vals = cls._format.unpack(msg)
        else:
            vals = tuple(map(kwargs.pop, cls._fields, cls._defaults))
            if kwargs:
                raise TypeError(
  "constructor got unexpected keyword argument '%s'" % kwargs.popitem()[0] )
            msg = cls._format.pack(*vals)
        assert isinstance(msg, bytes)
        assert isinstance(vals, tuple)
        return msg, vals

    def __repr__(self):
        repr = self.__class__.__name__ + '('
        repr += ', '.join('%s=%s' % x for x in zip(self._fields, self._vals))
        repr += ')'
        return repr


class _Header(_HeaderT, str):

    def __new__(cls, *args, **kwargs):
 
        msg, vals = cls._parse(*args, **kwargs)
        assert super(_Header, cls).__new__ is str.__new__
        self = super(_Header, cls).__new__(cls, msg)
        self._vals = vals
        return self


class _HeaderM(_HeaderT, bytearray):

    def __init__(self, *args, **kwargs):
        
        msg, vals = self._parse(*args, **kwargs)
        super(_HeaderM, self).__init__(msg)
        self._vals = vals


class ServerHeader(_Header):
    """client to server request header"""

    _fields = ('version', 'payload', 'type', 'flags', 'size', 'offset')
    _defaults = (0, 0, MSG_NOP, FLG_OWNET, _SCK_BUFSIZ, 0)


class ClientHeader(_Header):
    """server to client reply header"""

    _fields = ('version', 'payload', 'ret', 'flags', 'size', 'offset')
    _defaults = (0, 0, 0, FLG_OWNET, 0, 0)


class OwnetClientConnection(object):

    def __init__(self, sockaddr, family=socket.AF_INET, verbose=False):
        "establish a connection with server at sockaddr"
        
        self.verbose = verbose
        self.socket = socket.socket(family, socket.SOCK_STREAM)
        self.socket.settimeout(_SCK_TIMEOUT)
        self.socket.connect(sockaddr)
        if self.verbose:
            print self.socket.getsockname(), '->', self.socket.getpeername()

    def shutdown(self):
        "shutdown connection"
        self.socket.shutdown(socket.SHUT_RDWR)
        self.socket.close()

    def request(self, header, payload):
        "send message to server and return response"
        self._send_msg(header, payload)
        return self._read_msg()

    def _send_msg(self, header, payload):
        "send message to server"
        if self.verbose:
            print '->', repr(header)
            print '..', repr(payload)
        assert header.payload == len(payload)
        sent = self.socket.send(header + payload)
        if sent < len(header + payload):
            raise ShortWrite()
        assert sent == len(header + payload), sent
        
    def _read_msg(self):
        "read message from server"
        header = self.socket.recv(ClientHeader.hsize)
        if len(header) < ClientHeader.hsize:
            raise ShortRead('Error reading ClientHeader, got %s' % repr(header))
        assert(len(header) == ClientHeader.hsize)
        header = ClientHeader(header)
        if self.verbose: 
            print '<-', repr(header)
        if header.version != 0:
            raise ProtocolError('got malformed header: %s "%s"' % 
                                    (repr(header), header))
        if header.payload > _MAX_PAYLOAD:
            raise ProtocolError('huge data, unwilling to read: %s "%s"' %
                                    (repr(header), header))
        if header.payload > 0:
            payload = self.socket.recv(header.payload)
            if len(payload) < header.payload:
                raise ShortRead('got %s' % repr(header)+':'+repr(payload))
            if self.verbose: 
                print '..', repr(payload)
            assert header.size <= header.payload
            payload = payload[:header.size]
        else:
            payload = ''
        return header, payload


class OwnetProxy(object):
    """proxy owserver"""

    def __init__(self, host='localhost', port=4304, flags=0, 
                 verbose=False, ):
        try:
            gai = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
        except socket.gaierror as exp:
            raise ConnError(*exp.args)
        lastexp = None
        for (family, _, _, _, sockaddr) in gai:
            try:
                conn = OwnetClientConnection(sockaddr, family, verbose)
            except socket.error as lastexp:
                continue
            else:
                conn.shutdown()
            self._sockaddr, self._family = sockaddr, family
            break
        else:
            assert isinstance(lastexp, socket.error)
            assert isinstance(lastexp, IOError)
            raise ConnError(*lastexp.args)
        
        self.verbose = verbose
        self.flags = flags

    def _send_request(self, header, payload):
        try:
            conn = OwnetClientConnection(self._sockaddr, self._family, 
                       self.verbose)
            rep = conn.request(header, payload)
            conn.shutdown()
        except IOError as exp:
            raise ConnError(*exp.args)
        return rep

    def ping(self):
        "check connection"
        resp, data =  self._send_request(ServerHeader(),'')
        if (resp, data) != (ClientHeader(), ''):
            raise OwnetError(-resp.ret, '')

    def present(self, path):
        "check presence of sensor"
        path += '\x00'
        sheader = ServerHeader(payload=len(path), type=MSG_PRESENCE, 
            flags=self.flags, )
        cheader, data = self._send_request(sheader, path)
        assert len(data) == 0
        if cheader.ret < 0:
            return False
        else:
            assert cheader.ret == 0
            return True
        

    def dir(self, path, slash=True, bus=False):
        "li = dir(path)"
        # build message
        path += '\x00'
        sheader = ServerHeader(payload=len(path), type=MSG_DIRALLSLASH,
            flags=self.flags, )
        # chat
        cheader, data = self._send_request(sheader, path)
        # check reply
        if cheader.ret < 0:
            raise OwnetError(-cheader.ret, '', path[:-1])
        if data:
            return data.split(',')
        else:
            return []

    def read(self, path):
        "val = read(path)"
        # build message
        path += '\x00'
        sheader = ServerHeader(payload=len(path), type=MSG_READ, 
            flags=self.flags, )
        # chat
        cheader, data = self._send_request(sheader, path)
        # chek reply
        if cheader.ret < 0:
            raise OwnetError(-cheader.ret, '', path[:-1])
        return data


def test():
    data = ('temperature', 'HIH3600/humidity', 'udate')
    proxy = OwnetProxy(host='localhost', verbose=False)
    sensors = proxy.dir('/')
    for i in sensors:
        print i,
        for j in data:
            print proxy.read(i+j),
        print

if __name__ == '__main__':
    print __file__
    test()
