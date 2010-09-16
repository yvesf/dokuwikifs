#!/usr/bin/env python

# based on dokufucker.py see:
# http://www.dokuwiki.org/tips:edit_dokuwiki_with_text_editors_using_fuse_and_python

# while true; do sudo python dokuwikifs.py -o allow_other,gid=1006,uid=1006 -f test; echo restart; sleep 1; done

import errno
import fuse
import stat
import time
import logging
from dokuwikixmlrpc import DokuWikiClient

logging.basicConfig(level=logging.DEBUG)
 
 
if not hasattr(fuse, '__version__'):
    raise RuntimeError, \
        "your fuse-py doesn't know of fuse.__version__, probably it's too old."
 
fuse.fuse_python_api = (0, 2)

class DokuPage(fuse.Stat):
    def __init__(self,path,properties):
        self.path = path
        self.properties = properties
        
        self.st_mode = stat.S_IFREG | 0444
        self.st_ino = 0
        self.st_dev = 0
        self.st_nlink = 1
        self.st_uid = 0
        self.st_gid = 0

        if properties.has_key("size"):
            self.st_size = properties['size']
        else:
            self.st_size = 0
        self.st_atime = properties['mtime']
        self.st_mtime = properties['mtime']
        self.st_ctime = properties['mtime']

    def __repr__(self):
        return "DokuPage path={0} properties={1}".format(self.path, self.properties)

class DokuFS(fuse.Fuse):
    usage = """Doku Wiki Fuse driver
... -o url="http://site.tld/lib/exe/xmlrpc.php" -o username="me" -o password="mysecret" ...

Dont forget to activate xmlrpc and allow access 
for your user account in localconfig.php on server-side.

Try -d to see whats going on
"""
    def __init__(self, *args, **kw):
        fuse.Fuse.__init__(self, *args, **kw)
        self.parser.add_option(mountopt="url",
                               help="Dokuwiki XMLRPC URL (including lib/exe/xmlrpc.php)")
        self.parser.add_option(mountopt="username",
                               help="Wiki Username")
        self.parser.add_option(mountopt="password",
                              help="Wiki Password")

        self.log = logging.getLogger("DokuFS")
        self.pagelistCache = None
        self.pagelistCacheTime = 0
        self.pagelistCacheTimeout = 5

    def fsinit(self):
        self.log.info("DokuFS init")
        self.dokuwiki = DokuWikiClient(self.cmdline[0].url,
                                       self.cmdline[0].username,
                                       self.cmdline[0].password)
        os.chdir("/")

    def statfs(self):
        """
            - f_bsize - preferred size of file blocks, in bytes
            - f_frsize - fundamental size of file blcoks, in bytes
                [if you have no idea, use the same as blocksize]
            - f_blocks - total number of blocks in the filesystem
            - f_bfree - number of free blocks
            - f_files - total number of file inodes
            - f_ffree - nunber of free file inodes
            """
        statfs = fuse.StatVFS()
        statfs.f_bfree = 99999999999999
        return statfs

    def getattr(self, path):
        self.log.info( "getattr({0})".format(path) )

        entry = self._findPageTreeEntry(path)

        if not entry:
            return -errno.ENOENT
        elif entry.__class__ == dict:
            self.log.info( "dir with {0} entries".format(len(entry)) )
            t = fuse.Stat()
            t.st_mode = stat.S_IFDIR | 0755
            t.st_blksize = 0
            t.st_nlink = 2
            t.st_size = 0
            return t
        elif entry.__class__ == DokuPage:
            self.log.info(entry)
            return entry
    def open ( self, path, flags ):
        self.log.info( "open({0}, {1})".format(path,flags) )
        entry = self._findPageTreeEntry(path)
        if not entry:
            return -errno.ENOSYS
        elif entry.__class__ == dict:
            return -errno.EISDIR
        else:
            return None #sucess

    def _pagelist(self,cache=True):
        if not self.pagelistCache \
                or self.pagelistCacheTime + self.pagelistCacheTimeout < time.time() \
                or not cache:
            self.pagelistCacheTime = time.time()
            self.pagelistCache = self.dokuwiki.pagelist("")

        return self.pagelistCache

    def _pagetree(self,cache=True):
        root = {}
        for page in self._pagelist(cache=cache):
            path = page['id'].split(":")
            myRoot = root
            for pathElem in path:
                if path[-1] == pathElem: #last path element -> filename
                    myRoot[pathElem + ".txt"] = DokuPage("/"+("/".join(path))+".txt", page)
                else:
                    if not myRoot.has_key(pathElem):
                        myRoot[pathElem] = dict()
                    myRoot = myRoot[pathElem]
        return root

    def _findPageTreeEntry(self, path, cache=True):
        path = path[1:].split("/")
        root = self._pagetree(cache=cache)
        for pathElem in path:
            if pathElem == '':
                continue
            if root.has_key(pathElem):
                root = root[pathElem]
            else:
                #path not in tree
                return None
        return root

    def readdir(self, path, offset):
        self.log.info( "readdir({0}, {1})".format(path, offset) )
        yield fuse.Direntry(".")
        yield fuse.Direntry("..")
        entry = self._findPageTreeEntry(path)
        if entry and entry.__class__ == dict:
            for name in entry.keys():
                yield fuse.Direntry(name)
        else:
            print "kein Verzeichniss {0}".format(path)

    def chmod(self, path, mode):
        print "chomd({0},{1})".format(path,mode)
        return -errno.EOPNOTSUPP
 
    def chown(self, path, user, group):
        print "chown({0},{1},{2})".format(path,user,group)
        return -errno.EOPNOTSUPP
 
    def truncate(self, path, length):
        self.log.info( "truncate({0},{1})".format(path, length) )
        if length == 0:
            self.log.info("Emulate truncate to zero by delete/unlink")
            self.unlink(path)
        else:
            entry = self._findPageTreeEntry(path)
            if not entry or entry.__class__ != DokuPage:
                return -errno.ENOENT

            buf = self.dokuwiki.page(entry.properties["id"])[:length]
            if self.write(path, buf, 0) != len(buf):
                return -errno.EIO
            else:
                return 0

    def rmdir(self, path):
        print "rmdir({0})".format(path)
        return -errno.EOPNOTSUPP

    def link(self, path):
        self.log.info( "EOPNOTSUPP link({0})".format(path) )
        return -errno.EOPNOTSUPP

    def rename(self, path):
        self.log.info( "EOPNOTSUPP rename({0})".format(path) )
        return -errno.EOPNOTSUPP

    def unlink(self, path):
        self.log.info( "unlink({0})".format(path) )
        entry = self._findPageTreeEntry(path)
        if entry.__class__ == DokuPage:
           r = self.write(path, "", 0)
           if r == 0:
               return 0
           else:
               return r
        else:
            self.log.info("EOPNOTSUPP unlink for {0}".format(entry))
            return -errno.EOPNOTSUPP

    def read(self, path, length, offset):
        self.log.info( "read({0},{1},{2})".format(path, length, offset) )
        entry = self._findPageTreeEntry(path)
        if not entry or entry.__class__ != DokuPage:
            return -errno.ENOENT

        buf = self.dokuwiki.page(entry.properties["id"])
        result = buf[offset:length+offset]
        return result.encode("utf-8")

    def mknod(self, path, mode, rdev):
        self.log.info("mknod: %s (mode %s, rdev %s)" % (path, oct(mode), rdev))
        if rdev != 0:
            self.log.error("rdev != 0 not supported")
            return -errno.EOPNOTSUPP

        if mode & 0770000 != stat.S_IFREG:
            self.log.error("mode != s_IFREG not supported")
            return -errno.EOPNOTSUPP
        
        if self._findPageTreeEntry(path,cache=False) is not None:
            return -errno.EEXIST

        pageid = path.replace("/", ":")[:-3] #strip - .txt
        #put page
        self.dokuwiki.put_page(pageid, "placeholder", "created by mknod() call", minor=True)
        if self._findPageTreeEntry(path,cache=False) is not None:
            return 0 #success
        else:
            return -errno.EIO

    def write(self, path, buf, offset):
        self.log.info( "write({0}, len(buf)={1}, {2})".format(path, len(buf), offset) )
        entry = self._findPageTreeEntry(path)
        if not entry or entry.__class__ != DokuPage:
            return -errno.ENOENT

        # Lock page to prevent race-conditions
        lockResult = self.dokuwiki.set_locks({'lock': [ entry.properties['id'] ], 'unlock':list()})
        if not entry.properties['id'] in lockResult['locked']:
            self.log.error( "Failed to lock page {0}. lockResult was {1}".format(entry.properties['id'], lockResult) )
            return -errno.EIO
        try:
            if offset == 0:
                self.dokuwiki.put_page(entry.properties['id'], buf, "write() by uid=TODO", minor=False)
            else:
                raise Exception("offset not supported")
        except Exception,e:
            self.log.error(str(e))
            # remove pagelock if write failed
            if len(buf) > 0:
                lockResult = self.dokuwiki.set_locks({'lock':list(), 'unlock': [ entry.properties['id'] ]})
                if not entry.properties['id'] in lockResult['unlocked']:
                    self.log.error( "Failed to UN-lock page {0}. lockResult was {1}".format(entry.properties['id'], lockResult) )
                    return -errno.EIO

        return len(buf)

 
server = DokuFS(version="%prog " + fuse.__version__,
                usage=DokuFS.usage)
server.parse(values=server, errex=1)
server.main()
