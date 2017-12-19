/* An interface to copyfile(3) on macOS */

#include "Python.h"

#include <copyfile.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>

// Only for xattr testing routines
#include <sys/xattr.h>

// Only for ACL testing routines
#include <sys/types.h>
#include <sys/acl.h>


#ifndef __APPLE__
#  error This extension is only for macOS.
#endif

#ifdef __cplusplus
extern "C" {
#endif


PyObject *shutil_SameFileError = NULL;
PyObject *shutil_SpecialFileError = NULL;


/* copyfile() ----------------------------------------------------------------*/

#define COPYFILE_METHOD_DEF \
    {"copyfile", (PyCFunction)fn_copyfile, METH_VARARGS|METH_KEYWORDS, NULL}

static PyObject *
fn_copyfile(PyObject *self, PyObject *args, PyObject *kwargs)
{
    int err;

    // Parse function arguments
    int follow = 1;
    char *src, *dst;

    static char *kwlist[] = {"src", "dst", "follow_symlinks", NULL};
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "ss|$p", kwlist, &src, &dst,
                                     &follow))
        return NULL;

    // Get information aboout the files before copying
    struct stat src_st, dst_st;
    err = (follow ? stat : lstat)(src, &src_st);
    if (err != 0) {
        PyErr_SetFromErrnoWithFilenameObject(PyExc_OSError,
                                             PyUnicode_FromString(src));
        return NULL;
    }

    // XXX
    // shutil.copyfile() *only* checks if src is a FIFO. But the documentation
    // says other types of special files are not allowed either.
    if (!S_ISREG(src_st.st_mode) && !S_ISLNK(src_st.st_mode)) {
        PyErr_Format(shutil_SpecialFileError,
                     "`%s` is not a regular file or symbolic link", src);
        return NULL;
    }

    // If the destination exists, we can look into it as well
    err = stat(dst, &dst_st);
    if (err == 0) {
        // If the destination is a directory, they probably wanted copy()
        if (S_ISDIR(dst_st.st_mode)) {
            errno = EISDIR;
            PyErr_SetFromErrnoWithFilenameObject(PyExc_OSError,
                                                 PyUnicode_FromString(dst));
            return NULL;
        }

        // XXX
        // shutil.copyfile() checks if dst is a FIFO, and raises a
        // shutil.SpecialFileError if so.
        if (S_ISFIFO(dst_st.st_mode)) {
            PyErr_Format(shutil_SpecialFileError,
                         "`%s` is a named pipe", dst);
            return NULL;
        }

        // As of Python 3.4, if src and dst are the same file, shutil.copyfile()
        // raises a shutil.SameFileError exception.
        if (src_st.st_dev == dst_st.st_dev && src_st.st_ino == dst_st.st_ino) {
            PyErr_Format(shutil_SameFileError,
                         "'%s' and '%s' are the same file", src, dst);
            return NULL;
        }
    }

    // Perform the copy
    copyfile_flags_t flags = COPYFILE_DATA;
    if (!follow)
        flags |= COPYFILE_NOFOLLOW_SRC;
    err = copyfile(src, dst, NULL, flags);

    // Raise OSError if there is a problem. copyfile() sets errno for us.
    if (err != 0) {
        PyErr_SetFromErrnoWithFilenameObjects(PyExc_OSError,
                                              PyUnicode_FromString(src),
                                              PyUnicode_FromString(dst));
        return NULL;
    }

    // As of Python 3.3, shutil.copyfile() returns dst
    return PyUnicode_FromString(dst);
}


/* xattr testing routines ----------------------------------------------------*/

// These are for running tests. See the comment in test__copyfile.py.

#define _GETXATTR_METHOD_DEF \
    {"_getxattr", (PyCFunction)fn__getxattr, METH_VARARGS, NULL}

static PyObject *
fn__getxattr(PyObject *self, PyObject *args)
{
    // Parse function arguments
    char *path, *name;
    if (!PyArg_ParseTuple(args, "ss", &path, &name))
        return NULL;

    // Ask for the size of the attribute before we retrieve it
    ssize_t len = getxattr(path, name, NULL, 0, 0, XATTR_NOFOLLOW);
    if (len < 0) {
        PyErr_SetFromErrnoWithFilenameObject(PyExc_OSError,
                                             PyUnicode_FromString(path));
        return NULL;
    }

    // Special case: when len is zero, we don't need to getxattr again
    if (len == 0)
        return PyBytes_FromStringAndSize(NULL, 0);

    // Otherwise create a buffer and write into it
    char *buffer = PyMem_New(char, (size_t)len);
    ssize_t len2 = getxattr(path, name, buffer, len, 0, XATTR_NOFOLLOW);
    if (len2 < 0) {
        PyErr_SetFromErrnoWithFilenameObject(PyExc_OSError,
                                             PyUnicode_FromString(path));
        PyMem_Del(buffer);
        return NULL;
    } else if (len != len2) {
        // XXX We don't do anything here, but we could.
        /*
        errno = EIO; // I/O error, vague enough
        PyErr_SetFromErrnoWithFilenameObject(PyExc_OSError,
                                             PyUnicode_FromString(path));
        PyMem_Del(buffer);
        return NULL;
        */
    }

    PyObject *bytes = PyBytes_FromStringAndSize(buffer, len2);
    PyMem_Del(buffer);
    return bytes;
}


#define _SETXATTR_METHOD_DEF \
    {"_setxattr", (PyCFunction)fn__setxattr, METH_VARARGS, NULL}

static PyObject *
fn__setxattr(PyObject *self, PyObject *args)
{
    // Parse function arguments
    char *path, *name;
    Py_buffer value;
    if (!PyArg_ParseTuple(args, "ssy*", &path, &name, &value))
        return NULL;

    // Set the attribute
    int err = setxattr(path, name, value.buf, value.len, 0, XATTR_NOFOLLOW);
    if (err != 0) {
        PyErr_SetFromErrnoWithFilenameObject(PyExc_OSError,
                                             PyUnicode_FromString(path));
        return NULL;
    }

    Py_RETURN_NONE;
}


/* ACL testing routines ------------------------------------------------------*/

// These are for running tests only.

#define _GETACL_METHOD_DEF \
    {"_getacl", (PyCFunction)fn__getacl, METH_VARARGS, NULL}

static PyObject *
fn__getacl(PyObject *self, PyObject *args)
{
    // Parse function arguments
    char *path;
    if (!PyArg_ParseTuple(args, "s", &path))
        return NULL;

    // Try to read the ACL on the file
    // XXX As of Libc-1244.1.7, ACL_TYPE_EXTENDED is the only supported type
    acl_t acl = acl_get_link_np(path, ACL_TYPE_EXTENDED);
    if (!acl) {
        PyErr_SetFromErrnoWithFilenameObject(PyExc_OSError,
                                             PyUnicode_FromString(path));
        return NULL;
    }

    // Convert the ACL to text and return it
    char *text = acl_to_text(acl, NULL);
    PyObject *pytext = PyUnicode_FromString(text);
    free(text);  // not PyMem_RawFree?
    return pytext;
}


#define _SETACL_METHOD_DEF \
    {"_setacl", (PyCFunction)fn__setacl, METH_VARARGS, NULL}

static PyObject *
fn__setacl(PyObject *self, PyObject *args)
{
    // Parse function arguments
    char *path, *aclstr;
    if (!PyArg_ParseTuple(args, "ss", &path, &aclstr))
        return NULL;

    // Try to parse the text
    acl_t acl = acl_from_text(aclstr);
    if (!acl) {
        PyErr_SetFromErrno(PyExc_OSError);
        return NULL;
    }

    // Try to set the ACL on the file
    // XXX As of Libc-1244.1.7, ACL_TYPE_EXTENDED is the only supported type
    int err = acl_set_file(path, ACL_TYPE_EXTENDED, acl);
    acl_free(acl);
    if (err != 0) {
        PyErr_SetFromErrnoWithFilenameObject(PyExc_OSError,
                                             PyUnicode_FromString(path));
        return NULL;
    }

    Py_RETURN_NONE;
}


/* ---------------------------------------------------------------------------*/

static struct PyMethodDef _copyfile_functions[] = {
    COPYFILE_METHOD_DEF,
    _GETXATTR_METHOD_DEF,
    _SETXATTR_METHOD_DEF,
    _GETACL_METHOD_DEF,
    _SETACL_METHOD_DEF,
    {NULL, NULL}
};

static struct PyModuleDef _copyfile_module = {
    PyModuleDef_HEAD_INIT,
    "_copyfile",
    NULL,
    -1,
    _copyfile_functions,
    NULL,
    NULL,
    NULL,
    NULL
};

PyMODINIT_FUNC
PyInit__copyfile(void)
{
    PyObject *m;

    m = PyModule_Create(&_copyfile_module);
    if (m == NULL)
        return NULL;

    // We need to reach into shutil for a few exceptions
    PyObject *shutil = PyImport_ImportModule("shutil");
    if (!shutil)
        return NULL;

    shutil_SameFileError    = PyDict_GetItemString(PyModule_GetDict(shutil),
                                                   "SameFileError");
    shutil_SpecialFileError = PyDict_GetItemString(PyModule_GetDict(shutil),
                                                   "SpecialFileError");
    if (!shutil_SameFileError || !shutil_SpecialFileError)
        return NULL;

    return m;
}

#ifdef __cplusplus
}
#endif
