/* An interface to copyfile(3) on macOS */

#include "Python.h"

#include <fcntl.h>
#include <copyfile.h>
#include <sys/stat.h>


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
            PyErr_Format(shutil_SpecialFileError,
                         "`%s` is a directory. "
                         "Did you want to use shutil.copy?", dst);
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


/* ---------------------------------------------------------------------------*/

static struct PyMethodDef _copyfile_functions[] = {
    COPYFILE_METHOD_DEF,
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
