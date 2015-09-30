from __future__ import print_function
from logging import getLogger
from infi.pyutils.contexts import contextmanager
from infi.traceback import traceback_decorator
from .util import LOGGING_FORMATTER_KWARGS, STRFTIME_SHORT, get_timestamp

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
        target.close()

@contextmanager
def create_temporary_directory_for_log_collection(creation_dir, parent_dir_name, timestamp):
    from tempfile import mkdtemp
    from shutil import rmtree
    from os import path, makedirs
    from socket import gethostname
    tempdir = mkdtemp(dir=creation_dir)
    collect_dir = path.join(tempdir, parent_dir_name)
    specific_dir = path.join(collect_dir, gethostname(), timestamp.strftime(STRFTIME_SHORT))
    for dirname in ["commands", "files", "collection-logs"]:
        makedirs(path.join(specific_dir, dirname))
    def onerror(function, path, exc_info):
        logger.debug("Failed to delete {!r}".format(path))
    try:
        yield collect_dir, specific_dir
    finally:
        rmtree(tempdir, onerror=onerror)


def get_tar_path(prefix, output_path, timestamp, creation_dir=None):
    from os import close, remove, path
    from tempfile import mkstemp
    fd, archive_path = mkstemp(suffix=".tar.gz", prefix="{}-logs.{}-".format(prefix, timestamp.strftime(STRFTIME_SHORT)),
                               dir=creation_dir)
    close(fd)
    remove(archive_path)

    if output_path is None:
        return archive_path

    if path.isdir(output_path):
        return path.join(output_path, path.basename(archive_path))

    return output_path


@contextmanager
def log_collection_context(logging_memory_handler, tempdir, prefix, timestamp, output_path=None, creation_dir=None):
    from logging import root, DEBUG
    path = get_tar_path(prefix, output_path, timestamp, creation_dir)
    root.addHandler(logging_memory_handler)
    root.setLevel(DEBUG)
    try:
        yield path
    finally:
        with open_archive(path) as archive:
            root.removeHandler(logging_memory_handler)
            logging_memory_handler.flush()
            logging_memory_handler.close()
            add_directory(archive, tempdir)
            print("Logs collected successfully to {}".format(path))


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


def user_wants_to_collect(item):
    return raw_input('Do you want to collect {} [y/N]? '.format(item)).lower() in ('y', 'yes')


def collect(item, tempdir, timestamp, delta, silent, interactive=False):
    from colorama import Fore
    from sys import stdout
    if interactive and not user_wants_to_collect(item):
        return
    logger.info("Collecting {!r}".format(item))
    if not silent:
        print("Collecting {} ... ".format(item), end='')
    try:
        stdout.flush()
    except:
        pass # ignore "IOError: [Errno 9] Bad file descriptor" when running through the GUI on Windows
    try:
        item.collect(tempdir, timestamp, delta)
        logger.info("Collected  {!r} successfully".format(item))
        if not silent:
            print(Fore.GREEN + "ok" + Fore.RESET)
        return True
    except:
        logger.exception("An error ocurred while collecting {!r}".format(item))
        if not silent:
            print(Fore.MAGENTA + "error" + Fore.RESET)
        return False


@traceback_decorator
def run(prefix, items, timestamp, delta, output_path=None, creation_dir=None, parent_dir_name="logs", silent=False, interactive=False):
    """ collects log items and creates an archive with all collected items.
    items is a list of instances of 'Item' subclasses (see the collectables submodule).
    timestamp and delta indicate the timeframe of logs that need to be collected.
    The timeframe starts at (timestamp - delta) and ends at (timestamp).
    creation_dir is a path to a directory where the logs will be collected in. The function will create a temporary
    directory and then remove it when done. It will also be used for the final archive path, unless specified
    otherwise by output_path.
    This parameter is optional and will default to the system temporary directory, as decided by the tempfile module.
    output_path indicates the path where the final archive will be created. This may be a directory path or a full
    filename path.
    By default, the system uses the creation_dir for the directory, and generates an archive name using 'prefix'
    and the current time.
    parent_dir_name is the name of the parent directory that will be created inside the output archive.
    silent specified whether or not to print the process to stdout. pass True to silence the prints. The process
    will still be logged to a file under 'collection-logs' in the creation directory. """
    end_result = True
    with create_temporary_directory_for_log_collection(creation_dir, parent_dir_name, timestamp) as (tempdir, runtime_dir):
        with create_logging_handler_for_collection(runtime_dir, prefix) as handler:
            with log_collection_context(handler, tempdir, prefix, timestamp, output_path, creation_dir) as archive_path:
                kwargs = dict(prefix=prefix, timestamp=timestamp, delta=delta, output_path=output_path,
                              creation_dir=creation_dir, parent_dir_name=parent_dir_name)
                logger.info("Starting log collection with kwargs {!r}".format(kwargs))
                for item in items:
                    result = collect(item, runtime_dir, timestamp, delta, silent, interactive)
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
