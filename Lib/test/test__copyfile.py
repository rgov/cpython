'''
The goal of the _copyfile extension module is to mimic the behavior of shutil's
family of copy functions (insofar as they are sensible).
'''
import _copyfile
import os
import stat
import sys
import tempfile
import traceback
import uuid
import unittest

# TODO:
# Of course, once shutil changes to using _copyfile under the hood, we will need
# a way to import the plain-Python module.
import shutil


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
                name = '%s_line-%d_%d_%s' % \
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

# Helper methods that check various file metadata

def is_regular_file(path):
    # Be sure to use os.lstat, so that we don't follow links!
    return stat.S_ISREG(os.lstat(path).st_mode)

def is_symlink(path):
    return stat.S_ISLNK(os.lstat(path).st_mode)

# Unit tests

@unittest.skipUnless(sys.platform == 'darwin', 'requires macOS')
class CopyfileTestCase(unittest.TestCase):
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
        _copyfile.copyfile(src, dst)
        with open(dst) as f:
            self.assertEqual(f.read(), contents)

    def test_copy_overwrite(self):
        contents1, contents2 = 'hello world', 'good night moon'
        src = self.fg.create_file(contents1)
        dst = self.fg.create_file(contents2)
        _copyfile.copyfile(src, dst)
        with open(dst) as f:
            self.assertEqual(f.read(), contents1)

    def test_copy_directory(self):
        src = self.fg.create_directory()
        dst = self.fg.create_filename()
        with self.assertRaises(shutil.SpecialFileError):
            _copyfile.copyfile(src, dst)

    def test_copy_into_directory(self):
        src = self.fg.create_file()
        dst = self.fg.create_directory()
        with self.assertRaises(shutil.SpecialFileError):
            _copyfile.copyfile(src, dst)

    def test_copy_samefile(self):
        src = self.fg.create_file()
        with self.assertRaises(shutil.SameFileError):
            _copyfile.copyfile(src, src)

    def test_follow_symlinks(self):
        contents = 'hello world'
        target = self.fg.create_file(contents)
        src = self.fg.create_symlink(target)
        dst = self.fg.create_filename()
        _copyfile.copyfile(src, dst, follow_symlinks=True)
        self.assertTrue(is_regular_file(dst))
        with open(dst) as f:
            self.assertEqual(f.read(), contents)

    def test_dont_follow_symlinks(self):
        target = self.fg.create_file()
        src = self.fg.create_symlink(target)
        dst = self.fg.create_filename('link')
        _copyfile.copyfile(src, dst, follow_symlinks=False)
        self.assertTrue(is_symlink(dst))
        self.assertEqual(os.readlink(src), os.readlink(dst))

    def test_copy_resource_fork(self):
        src = self.fg.create_file()
        dst = self.fg.create_filename()
        rsrcfork = lambda p: os.path.join(p, '..namedfork', 'rsrc')
        with open(rsrcfork(src), 'w') as f:
            f.write('hello world')
        _copyfile.copyfile(src, dst)
        self.assertFalse(os.path.exists(rsrcfork(dst)))
