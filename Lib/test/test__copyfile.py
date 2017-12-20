'''
The goal of the _copyfile extension module is to mimic the behavior of shutil's
family of copy functions (insofar as they are sensible).
'''
import os

# This environment variable disables the use of _copyfile in shutil, so that we
# can check that our behavior matches the original implementation.
#
# We must import shutil very early, or else it might be imported as a
# dependency of some other module without the environment being set up.
os.environ['SHUTIL_DO_NOT_USE__COPYFILE'] = '1'
import shutil

import _copyfile
import errno
import grp
import stat
import sys
import tempfile
import traceback
import uuid
import unittest


# Set to True and the temporary files will not be destroyed
DEBUG = False


# Helper class that creates various kinds of file in a temporary directory

class FileGenerator(object):
    def __init__(self):
        self.tempdir = tempfile.mkdtemp()
        self.counters = {}

    def destroy(self):
        shutil.rmtree(self.tempdir)

    def create_filename(self, kind='file'):
        # A little hack to get the name of the test who called us, so we can
        # make more useful filenames
        name = ''
        for frame in traceback.extract_stack(None):
            if frame.name.startswith('test_'):
                test, line = frame.name[5:], frame.lineno
                self.counters.setdefault((test, line), 0)
                self.counters[(test, line)] += 1
                name = '%s-line_%d-%d-%s' % \
                    (test, line, self.counters[(test, line)], kind)
                break
        else:
            name = '%s-%s' % (kind, uuid.uuid4())
        return os.path.join(self.tempdir, name)

    def create_file(self, contents=''):
        dst = self.create_filename()
        with open(dst, 'w') as f:
            f.write(contents)
        return dst

    def create_directory(self):
        dst = self.create_filename('dir')
        os.mkdir(dst)
        return dst

    def create_symlink(self, to):
        dst = self.create_filename('link')
        os.symlink(to, dst)
        return dst

    def create_hanging_symlink(self):
        to  = self.create_filename('doesnt_exist')
        dst = self.create_filename('bad_link')
        os.symlink(to, dst)
        return dst

    def create_fifo(self):
        raise NotImplementedError()

    def create_character_device(self):
        raise NotImplementedError()

    def create_block_device(self):
        raise NotImplementedError()

    def create_socket(self):
        raise NotImplementedError()

# Helper methods that operate on various kinds of file metadata

def is_regular_file(path):
    # Be sure to use os.lstat, so that we don't follow links!
    return stat.S_ISREG(os.lstat(path).st_mode)

def is_symlink(path):
    return stat.S_ISLNK(os.lstat(path).st_mode)

def get_file_mode(path):
    return stat.S_IMODE(os.lstat(path).st_mode)


# Unit tests

@unittest.skipUnless(sys.platform == 'darwin', 'requires macOS')
class XattrTestCase(unittest.TestCase):
    # XXX
    # The os module's family of xattr functions do not work on macOS. (The
    # 'xattr' module that Apple distributes with macOS is not part of the
    # standard distribution.)
    #
    # Therefore, the _copyfile module provides functions for reading and writing
    # extended attributes ONLY for testing purposes.

    @classmethod
    def setUpClass(cls):
        cls.fg = FileGenerator()

    @classmethod
    def tearDownClass(cls):
        if DEBUG:
            print()
            print('Keeping working directory for', cls.__name__)
            print('  ' + cls.fg.tempdir)
        else:
            cls.fg.destroy()
        cls.fg = None

    def test_xattr_readwrite(self):
        name, value = 'org.python._copyfile.test', b'hello world'
        f = self.fg.create_file()
        _copyfile._setxattr(f, name, value)
        self.assertEqual(_copyfile._getxattr(f, name), value)

    def test_xattr_read_empty(self):
        name = 'org.python._copyfile.test'
        f = self.fg.create_file()
        _copyfile._setxattr(f, name, b'')
        self.assertEqual(_copyfile._getxattr(f, name), b'')

    def test_xattr_read_nonexistent(self):
        name = 'org.python._copyfile.test'
        f = self.fg.create_file()
        with self.assertRaises(OSError) as cm:
            _copyfile._getxattr(f, name)
        self.assertEqual(cm.exception.errno, errno.ENOATTR)


@unittest.skipUnless(sys.platform == 'darwin', 'requires macOS')
class ACLTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fg = FileGenerator()

    @classmethod
    def tearDownClass(cls):
        if DEBUG:
            print()
            print('Keeping working directory for', cls.__name__)
            print('  ' + cls.fg.tempdir)
        else:
            cls.fg.destroy()
        cls.fg = None

    def test_acl_readwrite(self):
        # XXX `chmod +a` actually uses a completely different ACL parser
        # (implemented in file_cmds/chmod_acl.c) than acl_from_text
        # (implemented in Libc/acl_translate.c)
        acl = '!#acl 1\nuser:00000000-0000-0000-0000-000000000000:::deny:read\n'
        f = self.fg.create_file()
        _copyfile._setacl(f, acl)
        self.assertEqual(_copyfile._getacl(f), acl)

    def test_acl_write_invalid(self):
        f = self.fg.create_file()
        with self.assertRaises(OSError) as cm:
            _copyfile._setacl(f, 'hello world')
        self.assertEqual(cm.exception.errno, errno.EINVAL)


@unittest.skipUnless(sys.platform == 'darwin', 'requires macOS')
class CopyfileTestCase(unittest.TestCase):
    module = _copyfile

    @classmethod
    def setUpClass(cls):
        cls.fg = FileGenerator()

    @classmethod
    def tearDownClass(cls):
        if DEBUG:
            print()
            print('Keeping working directory for', cls.__name__)
            print('  ' + cls.fg.tempdir)
        else:
            cls.fg.destroy()
        cls.fg = None

    def test_copy_regular_file(self):
        contents = 'hello world'
        src = self.fg.create_file(contents)
        dst = self.fg.create_filename()
        self.module.copyfile(src, dst)
        with open(dst) as f:
            self.assertEqual(f.read(), contents)

    def test_copy_overwrite(self):
        contents1, contents2 = 'hello world', 'good night moon'
        src = self.fg.create_file(contents1)
        dst = self.fg.create_file(contents2)
        self.module.copyfile(src, dst)
        with open(dst) as f:
            self.assertEqual(f.read(), contents1)

    def test_copy_directory(self):
        src = self.fg.create_directory()
        dst = self.fg.create_filename()
        with self.assertRaises(IsADirectoryError):
            self.module.copyfile(src, dst)

    def test_copy_into_directory(self):
        src = self.fg.create_file()
        dst = self.fg.create_directory()
        with self.assertRaises(IsADirectoryError):
            self.module.copyfile(src, dst)

    def test_copy_samefile(self):
        src = self.fg.create_file()
        with self.assertRaises(shutil.SameFileError):
            self.module.copyfile(src, src)

    def test_follow_src_symlink(self):
        contents = 'hello world'
        target = self.fg.create_file(contents)
        src = self.fg.create_symlink(target)
        dst = self.fg.create_filename()
        self.module.copyfile(src, dst, follow_symlinks=True)
        self.assertTrue(is_regular_file(dst))
        with open(dst) as f:
            self.assertEqual(f.read(), contents)

    def test_dont_follow_src_symlink(self):
        target = self.fg.create_file()
        src = self.fg.create_symlink(target)
        dst = self.fg.create_filename('link')
        self.module.copyfile(src, dst, follow_symlinks=False)
        self.assertTrue(is_symlink(dst))
        self.assertEqual(os.readlink(src), os.readlink(dst))

    def test_follow_dst_symlink(self):
        contents = 'hello world'
        target = self.fg.create_file() # this file will be overwritten
        src = self.fg.create_file(contents)
        dst = self.fg.create_symlink(target)
        self.module.copyfile(src, dst, follow_symlinks=True)
        self.assertTrue(is_symlink(dst))
        with open(target) as f:
            self.assertEqual(f.read(), contents)

    def test_follow_dst_hanging_symlink(self):
        contents = 'hello world'
        target = self.fg.create_filename() # this file doesn't exist yet
        src = self.fg.create_file(contents)
        dst = self.fg.create_symlink(target)
        self.module.copyfile(src, dst, follow_symlinks=True)
        self.assertTrue(is_symlink(dst))
        self.assertTrue(is_regular_file(target)) # should exist now
        with open(target) as f:
            self.assertEqual(f.read(), contents)

    # Explanation: follow_symlinks=False only affects src; if dst is a symlink
    # it is always followed.
    def test_always_follow_dst_symlink(self):
        contents1, contents2 = 'hello world', 'goodnight moon'
        target = self.fg.create_file(contents1) # this file will be overwritten
        src = self.fg.create_file(contents2)
        dst = self.fg.create_symlink(target)
        self.module.copyfile(src, dst, follow_symlinks=False)
        self.assertTrue(is_symlink(dst)) # still a symlink
        with open(target) as f:
            self.assertEqual(f.read(), contents2)

    def test_copy_resource_fork(self):
        src = self.fg.create_file()
        dst = self.fg.create_filename()
        rsrcfork = lambda p: os.path.join(p, '..namedfork', 'rsrc')
        with open(rsrcfork(src), 'w') as f:
            f.write('hello world')
        self.module.copyfile(src, dst)
        self.assertFalse(os.path.exists(rsrcfork(dst)))

    def test_copy_mode(self):
        src = self.fg.create_file()
        dst = self.fg.create_filename()
        mode = get_file_mode(src) ^ stat.S_IWGRP  # flip some bit
        os.chmod(src, mode)
        self.module.copyfile(src, dst)
        self.assertNotEqual(get_file_mode(dst), mode)

    def test_copy_group(self):
        src = self.fg.create_file()
        dst = self.fg.create_filename()
        gid = grp.getgrnam('everyone').gr_gid
        self.assertNotEqual(gid, -1)  # group does not exist
        self.assertNotEqual(os.lstat(src).st_gid, gid)  # wasn't already set
        os.chown(src, -1, gid)
        self.assertEqual(os.lstat(src).st_gid, gid)  # set successfully
        self.module.copyfile(src, dst)
        self.assertNotEqual(os.lstat(dst).st_gid, gid)  # not copied

    def test_copy_flags(self):
        src = self.fg.create_file()
        dst = self.fg.create_filename()
        flags = os.lstat(src).st_flags ^ stat.UF_HIDDEN # flip some flag
        os.lchflags(src, flags)
        self.module.copyfile(src, dst)
        self.assertNotEqual(os.lstat(dst).st_flags, flags)

    def test_copy_restricted_flags(self):
        # As of macOS 10.10, copyfile(3) will *not* copy the SF_RESTRICTED flag
        # (unless the destination directory also has it set)
        src = '/System/Library/CoreServices/SystemVersion.plist'
        dst = self.fg.create_filename()
        self.assertNotEqual(os.lstat(src).st_flags & stat.SF_RESTRICTED, 0)
        self.module.copyfile(src, dst)
        self.assertEqual(os.lstat(dst).st_flags & stat.SF_RESTRICTED, 0)

    def test_copy_acls(self):
        acl = '!#acl 1\nuser:00000000-0000-0000-0000-000000000000:::deny:read\n'
        src = self.fg.create_file()
        dst = self.fg.create_filename()
        _copyfile._setacl(src, acl)
        self.module.copyfile(src, dst)
        # For whatever reason, if the ACL doesn't exist, this is the exception
        with self.assertRaises(FileNotFoundError):
            _copyfile._getacl(dst)

    def test_copy_xattrs(self):
        name, value = 'org.python.self.module.test', b'hello world'
        src = self.fg.create_file()
        dst = self.fg.create_filename()
        _copyfile._setxattr(src, name, value)
        self.module.copyfile(src, dst)
        with self.assertRaises(OSError) as cm:
            _copyfile._getxattr(dst, name)
        self.assertEqual(cm.exception.errno, errno.ENOATTR)


# We also run the same test cases against shutil as a cross-check to make sure
# our behavior is the same
class ShutilTestCase(CopyfileTestCase):
    module = shutil
