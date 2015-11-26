Changelog
=========

v0.8.3 (devel)
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

v0.8.2 2015-08-26
  base for changelog
