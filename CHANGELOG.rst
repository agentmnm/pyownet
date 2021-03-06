Changelog
=========

v0.9.0 (2016-01-04)
-------------------

No major new features, API cleanup to ensure that connections are
properly closed. Functions that return binary data return ``bytes``.

* implement dummy context management protocol for ``_Proxy``
  for consitency with _PersistentProxy
* ``OwnetProxy`` class deprecated
* create a diagnostics directory ``./diags``
* move test suite from ``./test`` to ``./tests``
* ``pyownet.protocol._OwnetConnection.req()`` returns ``bytes`` and not
  ``bytearray``

  This is due to a simplification in
  ``pyownet.protocol._OwnetConnection._read_socket()`` method.
* better connection logic in ``pyownet.protocol.proxy()`` factory:
  first connect or raise ``protocol.ConnError``,
  then test owserver protocol or raise ``protocol.ProtocolError``
* use relative imports in ``pyownet.protocol``
* ``./test`` and ``./examples`` minor code refactor
* ``.gitignore`` cleanup (use only project specific ignores)
* add ``__del__`` in ``_PersistentProxy`` to ensure connection is closed
* use ``with _OwnetConnection`` inside ``_Proxy`` to shutdown sockets
* implement context management protocol for ``_OwnetConnection`` to
  guarantee that connection is shutdown on exit
* py26 testing via ``unittest2``
* transform ``./test`` directory in package, so that common code
  (used for reading configuration files) can be shared more easily
* move ``./pyownet`` to ``./src/pyownet``
