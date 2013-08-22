from __future__ import print_function
from logging import getLogger
from infi.pyutils.contexts import contextmanager
from infi.traceback import traceback_decorator
from .util import LOGGING_FORMATTER_KWARGS, get_timestamp

logger = getLogger(__name__)

@contextmanager
def create_logging_handler_for_collection(tempdir, prefix):
    from sys import maxsize
    from os import path
    from logging import FileHandler, DEBUG, Formatter
    from logging.handlers import MemoryHandler
    target = FileHandler(path.join(tempdir, "collection-logs", "{}.{}.debug.log".format(prefix, get_timestamp())))
    target.setFormatter(Formatter(**LOGGING_FORMATTER_KWARGS))
    handler = MemoryHandler(maxsize, target=target)
    handler.setLevel(DEBUG)
    try:
        yield handler
    finally:
        handler.close()

@contextmanager
def create_temporary_directory_for_log_collection(prefix):
    from tempfile import mkdtemp
    from shutil import rmtree
    from os import path, makedirs
    tempdir = mkdtemp(prefix="{}-logs".format(prefix))
    for dirname in ["collected-commands", "collected-files", "collection-logs"]:
        makedirs(path.join(tempdir, dirname))
    def onerror(function, path, exc_info):
        logger.debug("Failed to delete {!r}".format(path))
    try:
        yield tempdir
    finally:
        rmtree(tempdir, onerror=onerror)


def get_tar_path(prefix, optional_archive_path):
    from os import close, remove, path
    from tempfile import mkstemp
    fd, archive_path = mkstemp(suffix=".tar.gz", prefix="{}-logs.{}-".format(prefix, get_timestamp()))
    close(fd)
    remove(archive_path)

    if optional_archive_path is None:
        return archive_path

    if path.isdir(optional_archive_path):
        return path.join(optional_archive_path, path.basename(archive_path))

    return optional_archive_path


@contextmanager
def log_collection_context(logging_memory_handler, tempdir, prefix, optional_archive_path=None):
    from logging import root, DEBUG
    path = get_tar_path(prefix, optional_archive_path)
    root.addHandler(logging_memory_handler)
    root.setLevel(DEBUG)
    try:
        yield path
    finally:
        with open_archive(path) as archive:
            logging_memory_handler.flush()
            logging_memory_handler.close()
            add_directory(archive, tempdir)
            print("Logs collected successfully to {!r}".format(path))

@contextmanager
def open_archive(path):
    from tarfile import TarFile
    archive = TarFile.open(name=path, mode="w:gz", bufsize=16*1024)
    try:
        yield archive
    finally:
        archive.close()

def workaround_issue_10760(srcdir):
    # WORKAROUND for http://bugs.python.org/issue10760
    # Python's TarFile has issues with files have less data than the reported size
    # The workaround we did back in 2010 was to wrap TarFile objects with methods that work around that case,
    # But due to the structure of tar files, the workaround was a bit cumbersome
    # This time around, since we're already copying aside what we want to put in the archive, we can fix the files
    # before adding them to the archive
    from os import path, walk, stat
    for dirpath, dirnames, filenames in walk(srcdir):
        for filename in filenames:
            filepath = path.join(dirpath, filename)
            expected = stat(filepath).st_size
            actual = 0
            with open(filepath, 'rb') as fd:
                actual = bytes_read = len(fd.read(512))
                while bytes_read == 512:
                    bytes_read = len(fd.read(512))
                    actual += bytes_read
            if actual < expected:
                with open(filepath, 'ab') as fd:
                    fd.write('\x00' * (expected-actual))


def add_directory(archive, srcdir):
    from os.path import basename
    try:
        workaround_issue_10760(srcdir)
    except OSError:
        logger.exception("OSError")
    archive.add(srcdir, basename(srcdir))


def collect(item, tempdir, timestamp, delta):
    from colorama import Fore
    logger.info("Collecting {!r}".format(item))
    print("Collecting {} ... ".format(item), end='')
    try:
        item.collect(tempdir, timestamp, delta)
        logger.info("Collected  {!r} successfully".format(item))
        print(Fore.GREEN + "ok" + Fore.RESET)
        return True
    except:
        logger.exception("An error ocurred while collecting {!r}".format(item))
        print(Fore.MAGENTA + "error" + Fore.RESET)
        return False

@traceback_decorator
def run(prefix, items, timestamp, delta, optional_archive_path=None):
    end_result = True
    with create_temporary_directory_for_log_collection(prefix) as tempdir:
        with create_logging_handler_for_collection(tempdir, prefix) as handler:
            with log_collection_context(handler, tempdir, prefix, optional_archive_path) as archive_path:
                logger.info("Starting log collection")
                for item in items:
                    result = collect(item, tempdir, timestamp, delta)
                    end_result = end_result and result
                end_result = 0 if end_result else 1
                return end_result, archive_path


# TODO A web frontend that parser log collections
# Get by ftp
# Web frontend:
#     additional metadata -- description, tags, resolved (t/f)
#     sortable (customer, date, resolved/not)
#     link to JIRA
#     delete/bulk-delete
#     authentication
#     automatic analysis (e.g. not most recent version of power tools)
# View:
#     links to extracted files
