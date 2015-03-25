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

class FakeResult(object):
    @staticmethod
    def get_pid():
        return 0

    @staticmethod
    def get_returncode():
        return 0

    @staticmethod
    def get_stdout():
        return ''

    @staticmethod
    def get_stderr():
        return

def strip_os_prefix_from_path(path):
    import os
    return path.replace(os.environ.get("SYSTEMDRIVE", "C:"), '').lstrip(os.path.sep)

def reinit():
    try:
        from gevent import reinit as _reinit
        _reinit()
    except ImportError:
        pass

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
    reinit()
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
        try:
            last_modified_time = datetime.fromtimestamp(stat(filepath).st_mtime)
        except IOError, error:
            logger.debug("stat on filepath {!r} failed: {}".format(filepath, error))
            return False
        return last_modified_time >= (timestamp-delta) and last_modified_time <= (timestamp+delta)

    @classmethod
    def filter_old_files(cls, dirpath, filenames, timestamp, delta):
        # how we handle the case where files written after the timestamp may contain information about we need?
        #
        # v0.0.8 just collected all the files written after the timestamp
        #
        # starting with v0.0.9, we're collecting all the files that were last modified during:
        # (timestamp-deta) <= mtime <= (timestamp + delta)
        # this is good enough because:
        # when timestamp is _now_ and delta is not too small, files that are still being written (e.g syslog) wil be
        # colected as well
        # when timestamp is way back in the past and delta is big enough, it will catch the first file modified after
        # the timestamp, which will include all the data written within the timeframe, and possible more; this will
        # still capture files that were created after timestamp, but less than how much v0.0.8 captured, depending
        # on the size of the delta, ofcourse
        #
        # there are other, more accurate alternatives, but they base on knowledge of the collected file name and format
        # for example, if the namesare syslog{,.1,.2}, or we know that each line in the file starts with strptime
        return [filename for filename in
                filenames if cls.was_this_file_modified_recently(dirpath, filename, timestamp, delta)]

    @classmethod
    def collect_logfile(cls, src_directory, filename, dst_directory):
        import logging
        from shutil import copy2
        logger = logging.getLogger(__name__)
        src = path.join(src_directory, filename)
        dst = path.join(dst_directory, filename)
        try:
            copy2(src, dst)
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

    def start_process(self, target, *args, **kwargs):
        try:
            from gipc.gipc import _GProcess as Process
            from gipc.gipc import start_process as _start_process
            return _start_process(target, args=args, kwargs=kwargs)
        except ImportError:
            from multiprocessing import Process
            process = Process(target=target, args=args, kwargs=kwargs)
            process.start()
            return process

    def collect(self, targetdir, timestamp, delta):
        from logging import root
        from os import getpid
        # We want to copy the files in a child process, so in case the filesystem is stuck, we won't get stuck too
        kwargs = dict(dirname=self.dirname, regex_basename=self.regex_basename,
                      recursive=self.recursive, targetdir=path.join(targetdir, "files"),
                      timeframe_only=self.timeframe_only, timestamp=timestamp, delta=delta)
        try:
            [logfile_path] = [handler.target.baseFilename for handler in root.handlers
            if self._is_my_kind_of_logging_handler(handler)] or [None]
        except ValueError:
            logfile_path = None
        subprocess = self.start_process(multiprocessing_logger, logfile_path, getpid(), self.__class__.collect_process, **kwargs)
        subprocess.join(self.timeout_in_seconds)
        if subprocess.is_alive():
            msg = "Did not finish collecting {!r} within the {} seconds timeout_in_seconds"
            logger.error(msg.format(self, self.timeout_in_seconds))
            try:
                subprocess.terminate()
            except OSError:
                pass
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
    def __init__(self, executable, commandline_arguments=[], wait_time_in_seconds=60, prefix=None, env=None):
        """
        Define a command to run and collect its output.
        executable - name of the executable to run
        commandline_arguments - list of arguments to pass to the command
        wait_time_in_seconds - maximum time to wait for the command to finish
        prefix - optional prefix for the name of the output files (default: the executable name)
        env - a optional mapping of environment variables to run the command with
        """
        super(Command, self).__init__()
        self.executable = executable
        self.commandline_arguments = commandline_arguments
        self.wait_time_in_seconds = wait_time_in_seconds
        self.prefix = prefix
        self.env = env

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
        try:
            cmd = execute_async([executable] + self.commandline_arguments, env=self.env)
        except OSError:
            logger.error("executable {} not found".format(executable))
            return FakeResult
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
        output_format = "{prefix}.{timestamp}.{pid}.txt"
        kwargs = dict(prefix=self.prefix or executable_name, pid=pid, timestamp=timestamp)
        output_filename = output_format.format(**kwargs)
        with open(join(targetdir, output_filename), 'w') as fd:
            fd.write("\n==={}===:\n{}".format("command", ' '.join([executable_name] + self.commandline_arguments)))
            for output_type in ['returncode', 'stdout', 'stderr']:
                output_value = getattr(cmd, "get_{}".format(output_type))()
                fd.write("\n==={}===:\n{}".format(output_type, output_value))

    def collect(self, targetdir, timestamp, delta):
        cmd = self._execute()
        self._write_output(cmd, path.join(targetdir, "commands"))


class Script(Item):

    def __init__(self, script, wait_time_in_seconds=60, prefix=None, env=None):
        """
        Define a Python script to run and collect its output.
        script - a string containing the script
        wait_time_in_seconds - maximum time to wait for the script to finish
        prefix - optional prefix for the name of the output files (default: 'script')
        env - a optional mapping of environment variables to run the script with
        """
        super(Script, self).__init__()
        self.script = script
        self.wait_time_in_seconds = wait_time_in_seconds
        self.prefix = prefix or 'script'
        self.env = env

    def __repr__(self):
        return "<Script({})>".format(self.script)

    def __str__(self):
        return self.prefix

    def _create_script_file(self):
        from tempfile import mkstemp
        import os, sys
        fd, path = mkstemp(suffix='.py')
        os.close(fd)
        with open(path, 'wb') as f:
            f.write('import sys\nsys.path[0:0] = [\n')
            for entry in sys.path:
                f.write('\t%r,\n' % entry)
            f.write(']\n\n')
            f.write(self.script)
        return path

    def collect(self, targetdir, timestamp, delta):
        from sys import executable
        commandline_arguments = ['-S', self._create_script_file()]
        cmd = Command(executable, commandline_arguments, self.wait_time_in_seconds, self.prefix, self.env)
        cmd.collect(targetdir, timestamp, delta)


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
