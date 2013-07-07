from infi.pyutils.decorators import wraps
from logging import getLogger
from datetime import datetime
from re import match
from os import path, stat, getpid

logger = getLogger(__name__)

class Item(object): # pragma: no cover
    def collect(self, targetdir, timestamp, delta):
        raise NotImplementedError()

class TimeoutError(Exception):
    pass

def strip_os_prefix_from_path(path):
    import os
    return path.replace(os.environ.get("SYSTEMDRIVE", "C:"), '').lstrip(os.path.sep)

def multiprocessing_logger(logfile_path, parent_pid, func, *args, **kwargs):
    from sys import exit

    def setup_logging():
        import logging
        import os
        from .. import LOGGING_FORMATTER_KWARGS
        if logfile_path is None or parent_pid == os.getpid():  # in unittests
            return
        logging.root = logging.RootLogger(logging.DEBUG)
        logging.Logger.root = logging.root
        logging.Logger.manager = logging.Manager(logging.Logger.root)
        filename = logfile_path.replace(".debug.log", ".multiprocessing.debug.log")
        logging.basicConfig(filename=filename, level=logging.DEBUG,
                            format=LOGGING_FORMATTER_KWARGS['fmt'], datefmt=LOGGING_FORMATTER_KWARGS['datefmt'])

    import logging
    setup_logging()
    try:
        return func(*args, **kwargs)
    except:
        logger.exception("Caught an unhandled exception in child process")
        if logging.root.handlers:
            logging.root.handlers[0].close()
        exit(1)

class Directory(Item):
    def __init__(self, dirname, regex_basename='.*', recursive=False, timeout_in_seconds=60, timeframe_only=True):
        super(Directory, self).__init__()
        self.dirname = dirname
        self.regex_basename = regex_basename
        self.recursive = recursive
        self.timeout_in_seconds = timeout_in_seconds
        self.timeframe_only = timeframe_only

    def __repr__(self):
        try:
            msg = "<Directory(dirname={!r}, regex_basename={!r}, recursive={!r}, timeout_in_seconds={!r})>"
            return msg.format(self.dirname, self.regex_basename, self.recursive, self.timeout_in_seconds)
        except:
            return super(Directory, self).__repr__()

    def __str__(self):
        try:
            return "files {!r} from {}".format(self.regex_basename, self.dirname)
        except:
            return super(Directory, self).__str__()

    @classmethod
    def was_this_file_modified_recently(cls, dirpath, filename, timestamp, delta):
        import logging
        logger = logging.getLogger(__name__)
        filepath = path.join(dirpath, filename)
        if not path.isfile(filepath) or path.islink(filepath):
            logger.debug("{!r} is not a file, skipping it".format(filepath))
            return False
        last_modified_time = datetime.fromtimestamp(stat(filepath).st_mtime)
        return last_modified_time > timestamp-delta

    @classmethod
    def filter_old_files(cls, dirpath, filenames, timestamp, delta):
        # TODO handling the case where files written after the timestamp may contain information about we need
        # alternative #1 is to collect all the files written after the timestamp
        # alternative #2 is to collect only collect the first file written after the timestamp from each base
        # for example, from messages* collect all the files from the timeframe and the 1st one after it
        return [filename for filename in filenames if cls.was_this_file_modified_recently(dirpath, filename, timestamp, delta)]

    @classmethod
    def collect_logfile(cls, src_directory, filename, dst_directory):
        import logging
        from shutil import copy
        logger = logging.getLogger(__name__)
        src = path.join(src_directory, filename)
        dst = path.join(dst_directory, filename)
        try:
            copy(src, dst)
        except:
            logger.exception("Failed to copy {!r}".format(src))

    @classmethod
    def filter_matching_filenames(cls, filenames, pattern):
        return [filename for filename in filenames if match(pattern, filename)]

    @classmethod
    def collect_process(cls, dirname, regex_basename, recursive, targetdir, timeframe_only, timestamp, delta):
        import logging
        logger = logging.getLogger(__name__)
        logger.debug("Collection of {!r} in subprocess started".format(dirname))
        from os import walk, makedirs
        for dirpath, dirnames, filenames in walk(dirname):
            if dirpath != dirname and not recursive:
                continue
            relative_dirpath = strip_os_prefix_from_path(dirpath)
            dst_directory = path.join(targetdir, relative_dirpath)
            if not path.exists(dst_directory):
                makedirs(dst_directory)
            filenames = cls.filter_matching_filenames(filenames, regex_basename)
            filenames = cls.filter_old_files(dirpath, filenames, timestamp, delta) if timeframe_only else filenames
            logger.debug("Collecting {!r}".format(filenames))
            [cls.collect_logfile(dirpath, filename, dst_directory) for filename in filenames]
        logger.debug("Collection of {!r} in subprocess ended successfully".format(dirname))

    def _is_my_kind_of_logging_handler(self, handler):
        from logging.handlers import MemoryHandler
        from logging import FileHandler
        return isinstance(handler, MemoryHandler) and isinstance(handler.target, FileHandler)

    def collect(self, targetdir, timestamp, delta):
        from logging import root
        from multiprocessing import Process
        from os import getpid
        # We want to copy the files in a child process, so in case the filesystem is stuck, we won't get stuck too
        kwargs = dict(dirname=self.dirname, regex_basename=self.regex_basename,
                      recursive=self.recursive, targetdir=targetdir,
                      timeframe_only=self.timeframe_only, timestamp=timestamp, delta=delta)
        try:
            [logfile_path] = [handler.target.baseFilename for handler in root.handlers
            if self._is_my_kind_of_logging_handler(handler)] or [None]
        except ValueError:
            logfile_path = None
        subprocess = Process(target=multiprocessing_logger, args=(logfile_path, getpid(),
                                                                  Directory.collect_process), kwargs=kwargs)
        subprocess.start()
        subprocess.join(self.timeout_in_seconds)
        if subprocess.is_alive():
            msg = "Did not finish collecting {!r} within the {} seconds timeout_in_seconds"
            logger.error(msg.format(self, self.timeout_in_seconds))
            subprocess.terminate()
            if subprocess.is_alive():
                logger.info("Subprocess {!r} terminated".format(subprocess))
            else:
                logger.error("Subprocess {!r} is stuck".format(subprocess))
            raise TimeoutError()
        elif subprocess.exitcode:
            logger.error("Subprocess {!r} returned non-zero exit code".format(subprocess))
            raise RuntimeError(subprocess.exitcode)


class File(Directory):
    def __init__(self, filepath):
        from os import path
        self.filepath = filepath
        super(File, self).__init__(path.dirname(filepath), path.basename(filepath),
                                   recursive=False, timeframe_only=False)

def find_executable(executable_name):
    """Helper function to find executables"""
    from os import path, name, environ, pathsep
    from sys import argv
    executable_name = path.basename(executable_name)
    logger.debug("Looking for executable {}".format(executable_name))
    if name == 'nt':
        executable_name += '.exe'
    possible_locations = environ['PATH'].split(pathsep) if environ.has_key('PATH') else []
    possible_locations.insert(0, path.dirname(argv[0]))
    if name == 'nt':
        possible_locations.append(path.join(r"C:", "Windows", "System32"))
    else:
        possible_locations += [path.join(path.sep, 'sbin'),
                               path.join(path.sep, 'usr', 'bin'), path.join(path.sep, 'bin')]
    possible_executables = [path.join(location, executable_name) for location in possible_locations]
    existing_executables = [item for item in possible_executables if path.exists(item)]
    if not existing_executables:
        logger.debug("No executables found")
        return executable_name
    logger.debug("Found the following executables: {}".format(existing_executables))
    return existing_executables[0]

class Command(Item):
    def __init__(self, executable, commandline_arguments=[], wait_time_in_seconds=60, prefix=None):
        """
        Define a command to run and collect its output.
        executable - name of the executable to run
        commandline_arguments - list of arguments to pass to the command
        wait_time_in_seconds - maximum time to wait for the command to finish
        prefix - optional prefix for the name of the output files (default: the executable name)
        """
        super(Command, self).__init__()
        self.executable = executable
        self.commandline_arguments = commandline_arguments
        self.wait_time_in_seconds = wait_time_in_seconds
        self.prefix = prefix

    def __repr__(self):
        try:
            msg = "<Command(executable={!r}, commandline_arguments={!r}, wait_time_in_seconds={!r})>"
            return msg.format(self.executable, self.commandline_arguments, self.wait_time_in_seconds)
        except:
            super(Command, self).__repr__()

    def __str__(self):
        try:
            return ' '.join(["command", self.executable] + self.commandline_arguments)
        except:
            return super(Command, self).__str__()

    def _execute(self):
        from infi.execute import execute_async, CommandTimeout
        from os import path
        executable = self.executable if path.exists(self.executable) else find_executable(self.executable)
        logger.info("Going to run {} {}".format(executable, self.commandline_arguments))
        cmd = execute_async([executable] + self.commandline_arguments)
        try:
            cmd.wait(self.wait_time_in_seconds)
        except OSError, error:
            logger.exception("Command did not run")
        except CommandTimeout, error:
            logger.exception("Command did not finish in {} seconds, killing it".format(self.wait_time_in_seconds))
            cmd.kill()
            if not cmd.is_finished():
                cmd.kill(9)
            if not cmd.is_finished():
                logger.info("{!r} is stuck".format(cmd))
            else:
                logger.info("{!r} was killed".format(cmd))
        return cmd

    def _write_output(self, cmd, targetdir):
        from os.path import basename, join
        from ..util import get_timestamp
        executable_name = basename(self.executable).split('.')[0]
        pid = cmd.get_pid()
        timestamp = get_timestamp()
        output_format = "{prefix}.{timestamp}.{pid}.{output_type}.txt"
        kwargs = dict(prefix=self.prefix or executable_name, pid=pid, timestamp=timestamp,
                      cmdline=' '.join([executable_name] + self.commandline_arguments))
        for output_type in ['returncode', 'stdout', 'stderr']:
            kwargs.update(dict(output_type=output_type))
            output_filename = output_format.format(**kwargs)
            with open(join(targetdir, output_filename), 'w') as fd:
                fd.write(str(getattr(cmd, "get_{}".format(output_type))()))

    def collect(self, targetdir, timestamp, delta):
        cmd = self._execute()
        self._write_output(cmd, targetdir)

class Environment(Item):
    def collect(self, targetdir, timestamp, delta):
        from os import path, environ
        from json import dumps
        with open(path.join(targetdir, "environment.json"), 'w') as fd:
            fd.write(dumps(environ.copy(), indent=True))

    def __repr__(self):
        return "<Environment>"

    def __str__(self):
        return "environment variables"

class Hostname(Item):
    def collect(self, targetdir, timestamp, delta):
            from os import path
            from socket import gethostname
            from json import dumps
            with open(path.join(targetdir, "hostname.json"), 'w') as fd:
                fd.write(dumps(dict(hostname=gethostname()), indent=True))

    def __repr__(self):
        return "<Hostname>"

    def __str__(self):
        return "hostname"
