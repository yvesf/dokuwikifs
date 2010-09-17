#!/usr/bin/env python

# based on dokufucker.py see:
# http://www.dokuwiki.org/tips:edit_dokuwiki_with_text_editors_using_fuse_and_python

#while true; do sudo python dokuwikifs.py -f -o url="http://site/lib/exe/xmlrpc.php",username="foo",password="bla",allow_other testpath; sleep 1; done

import os
import errno
import fuse
import stat
import time
import logging
from xml.parsers.expat import ExpatError
from dokuwikixmlrpc import DokuWikiClient, DokuWikiXMLRPCError

logging.basicConfig(level=logging.DEBUG)

if not hasattr(fuse, '__version__'):
    raise RuntimeError, \
        "your fuse-py doesn't know of fuse.__version__, probably it's too old."
 
fuse.fuse_python_api = (0, 2)

def checkpath(path):
    """
    returns true if path is a clean dokuwiki id
    TODO and FIXME
    """
    filename = os.path.basename(path)
    dirname = os.path.dirname(path)
    logging.getLogger("checkpath").debug("filename={0} dirname={1} path={2}".format(filename,dirname, path))
    allowedChars = map(lambda char: chr(char), range(ord("a"),ord("z")+1))
    allowedChars.append(".")
    allowedChars.append("/")
    allowedChars.extend(map(lambda char: chr(char), range(ord("0"), ord("9")+1)))
    pathCharOk = True
    for pathChar in path:
        pathCharOk = pathCharOk and pathChar in allowedChars
    return ":" not in path \
        and ( len(filename)>0 
              and filename[0] not in (".")  
              or len(filename) == 0) \
        and pathCharOk

class DokuPage(fuse.Stat):
    def __init__(self,path,properties):
        self.path = path
        self.properties = properties
        
        self.st_mode = stat.S_IFREG | 0666
        self.st_ino = 0
        self.st_dev = 0
        self.st_nlink = 1
        self.st_uid = 0
        self.st_gid = 0

        self.st_size = properties['size']
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

    def init2(self):
        self.log.info("init2")
        try:
            self.dokuwiki = DokuWikiClient(self.url,
                                           self.username,
                                           self.password)
            self.log.info( "RPC Version: {0}".format(self.dokuwiki.rpc_version_supported()) )
            self._pagelist(cache=False)
        except Exception,e:
            self.log.error( "Exception {0}: {1}".format(e.__class__.__name__,str(e)))
            raise RuntimeError(e)

    def _pagelist(self,cache=True): #rethrows DokuWikiXMLRPCError
        if not self.pagelistCache \
                or self.pagelistCacheTime + self.pagelistCacheTimeout < time.time() \
                or not cache:
            self.pagelistCacheTime = time.time()
            self.pagelistCache = self.dokuwiki.pagelist("")

        return self.pagelistCache

    def _pagetree(self,cache=True):
        root = {}
        try:
            for page in self._pagelist(cache=cache):
                path = page['id'].split(":")
                myRoot = root
                for pathElem in path:
                    if path[-1] == pathElem: #last path element -> filename
                        myRoot[pathElem] = DokuPage("/"+("/".join(path)), page)
                    else:
                        if not myRoot.has_key(pathElem):
                            myRoot[pathElem] = dict()
                        myRoot = myRoot[pathElem]
        except DokuWikiXMLRPCError,e:
            self.log.error(str(e))
        finally:
            return root

    def _findPageTreeEntry(self, pathIn, cache=True):
        if not checkpath(pathIn):
            self.log.error("_findPageTreeEntry: Invalid path {0}".format(pathIn))
            return None

        path = pathIn[1:].split("/")
        root = self._pagetree(cache=cache)
        for pathElem in path:
            if pathElem == '':
                continue
            if root.has_key(pathElem):
                root = root[pathElem]
            else:
                self.log.debug( "_findPageTreeEntry({0},cache={1}): Path not found".format(pathIn,cache) )
                return None
        return root

    def fsinit(self):
        self.log.info("fsinit")
        os.chdir("/")
        
    def statfs(self):
        self.log.info("statfs()")
        statfs = fuse.StatVfs()
        statfs.f_bsize = 1                    #preferred size of file blocks, in bytes
        statfs.f_frsize = 1                   #fragment size
        statfs.f_blocks = 1024*1024*1024      #size of fs in f_frsize units
        statfs.f_bfree = 1024*1024*512        #free blocks
        statfs.f_bavail = statfs.f_bfree      #free blocks for unprivileged users
        statfs.f_files = 8192                 #inodes
        statfs.f_ffree = 8192                 #free inodes
        statfs.f_favail = statfs.f_ffree      #free inodes for unprivileged users
        return statfs

    def getattr(self, path):
        entry = self._findPageTreeEntry(path)
        if not entry:
            self.log.error( "getattr({0}): not found".format(path) )
            return -errno.ENOENT
        elif entry.__class__ == dict:
            self.log.info( "getattr({0}): dir with {1} entries".format(path, len(entry)) )
            t = fuse.Stat()
            t.st_mode = stat.S_IFDIR | 0777
            t.st_blksize = 0
            t.st_nlink = 2
            t.st_size = 0
            return t
        elif entry.__class__ == DokuPage:
            self.log.info( "getattr({0}): {1}".format(path, entry) )
            return entry

    def open ( self, path, flags ):
        self.log.info( "open({0}, {1})".format(path,flags) )
        entry = self._findPageTreeEntry(path)
        if not entry:
            self.log.info( "open({0}, {1}): file not found".format(path,flags) )
            return -errno.ENOSYS
        elif entry.__class__ == dict:
            self.log.info( "open({0}, {1}): -EISDIR is a directory".format(path,flags) )
            return -errno.EISDIR
        else:
            return None #success

    def readdir(self, path, offset):
        self.log.info( "readdir({0}, {1})".format(path, offset) )
        yield fuse.Direntry(".")
        yield fuse.Direntry("..")
        entry = self._findPageTreeEntry(path)
        if entry and entry.__class__ == dict:
            for name in entry.keys():
                yield fuse.Direntry( name )
        else:
            self.log.error("readdir({0},{1}): not a directory".format(path,offset))

    def chmod(self, path, mode):
        self.log.info( "EOPNOTSUPP chmod({0},{1})".format(path,mode) )
        return -errno.EOPNOTSUPP
 
    def chown(self, path, user, group):
        self.log.info( "EOPNOTSUPP chown({0},{1},{2})".format(path,user,group) )
        return -errno.EOPNOTSUPP
 
    def truncate(self, path, length):
        self.log.info( "truncate({0},{1})".format(path, length) )
        if length == 0:
            self.log.info("Emulate truncate to zero by writing placeholder")
            self.write(path, "%truncated%", 0)
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
        self.log.info( "EOPNOTSUPP rmdir({0})".format(path) )
        return -errno.EOPNOTSUPP

    def link(self, path):
        self.log.info( "EOPNOTSUPP link({0})".format(path) )
        return -errno.EOPNOTSUPP

    def rename(self, path, newpath):
        self.log.info( "EOPNOTSUPP rename({0},{1})".format(path,newpath) )
        return -errno.EOPNOTSUPP

    def unlink(self, path):
        self.log.info( "unlink({0})".format(path) )
        entry = self._findPageTreeEntry(path)
        if entry.__class__ == DokuPage:
           return self.write(path, "", 0)
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
            self.log.error("mknod rdev != 0 not supported")
            return -errno.EOPNOTSUPP

        if mode & 0770000 != stat.S_IFREG:
            self.log.error("mknod: mode != s_IFREG not supported")
            return -errno.EOPNOTSUPP
        
        if self._findPageTreeEntry(path,cache=False) is not None:
            self.log.error("mknod: file exists")
            return -errno.EEXIST

        if not checkpath(path):
            self.log.error("mknod: Invalid path {0}".format(path))
            return -errno.EIO

        #put page
        pageid = path.replace("/", ":")
        try:
            self.dokuwiki.put_page(pageid, "placeholder", "created by mknod() call", minor=True)
            self._pagetree(cache=False) #reread tree
            return 0 #success
        except DokuWikiXMLRPCError,e:
            return -errno.EIO

    def write(self, path, buf, offset):
        self.log.info( "write({0}, len(buf)={1}, {2})".format(path, len(buf), offset) )
        entry = self._findPageTreeEntry(path)
        if not entry or entry.__class__ != DokuPage:
            return -errno.ENOENT

        # Lock page to prevent race-conditions
        try:
            lockResult = self.dokuwiki.set_locks({'lock': [ entry.properties['id'] ], 'unlock':list()})
            if not entry.properties['id'] in lockResult['locked']:
                self.log.error( "Failed to lock page {0}. lockResult was {1}".format(entry.properties['id'], lockResult) )
                return -errno.EIO
        except DokuWikiXMLRPCError,e:
            self.log.error(str(e))
            return -errno.EIO

        try:
            if offset == 0:
                self.dokuwiki.put_page(entry.properties['id'], buf, "write() by uid=TODO", minor=False)
            else:
                raise Exception("offset not supported")
            if len(buf) == 0: #writing a empty dw-page is like removing it
                self._pagetree(cache=False)
        except (DokuWikiXMLRPCError,Exception),e:
            self.log.error(str(e))
            # remove pagelock if write failed
            if len(buf) > 0:
                try:
                    lockResult = self.dokuwiki.set_locks({'lock':list(), 'unlock': [ entry.properties['id'] ]})
                    if not entry.properties['id'] in lockResult['unlocked']:
                        self.log.error( "Failed to UN-lock page {0}. lockResult was {1}".format(entry.properties['id'], lockResult) )
                        return -errno.EIO
                except DokuWikiXMLRPCError,e2:
                    self.log.error(str(e2))
                    return -errno.EIO
        
        return len(buf)

 
dokuFS = DokuFS(version="%prog " + fuse.__version__,
                usage=DokuFS.usage)
dokuFS.parse(values=dokuFS, errex=1)
dokuFS.init2()
dokuFS.multithreaded = False
dokuFS.main()
