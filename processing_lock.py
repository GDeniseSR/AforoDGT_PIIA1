import msvcrt
import sys
import os
import logging

# Modfiy lock path. Forces there to only be one execution of the main program at the same time.
LOCKFILE = "C:/Users/gaela/arcgis_aforo.lock"

def acquire_lock():
    try:
        # Open/create lock file in binary mode
        lock_fd = open(LOCKFILE, 'w+b')
        # Try to lock the entire file exclusively, non-blocking
        msvcrt.locking(lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
        logging.debug("Lock obtained.")
        return lock_fd
    except (IOError, OSError):
        logging.warning("Previous execution still running. Exiting.")
        sys.exit(0)