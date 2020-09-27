
from logging import StreamHandler, getLogger, Formatter, FileHandler
from contextvars import ContextVar, copy_context
import asyncio
import logging
from asyncio import gather, get_event_loop
from logging import getLogger
from time import sleep
from typing import Callable, List
import uuid

import asyncssh
from asyncssh import SSHClient

correlation_id: ContextVar[List[str]] = ContextVar('correlation_id', default=[])

logger = logging.getLogger(__name__)

class CorrelationContextDecorator:
    _previous: List[str]
    _fn: Callable

    def __init__(self, fn):
        self._fn = fn

    def _push(self):
        self._previous = correlation_id.get()

        new_list = list(self._previous)
        new_list.append(str(uuid.uuid4()))

        correlation_id.set(new_list)

    def _pop(self):
        correlation_id.set(self._previous)

    def _create_decorator_async(self):

        # asyncio automatically sets up a new context for the call
        # https://docs.python.org/3.7/library/contextvars.html#asyncio-support
        async def _decorator_parent_ctx(*args, **kwargs):
            async def _decorator_in_child_ctx():
                self._push()
                try:
                    return await self._fn(*args, **kwargs)
                finally:
                    self._pop()

            return await _decorator_in_child_ctx()

        return _decorator_parent_ctx

    def _create_decorator(self):

        # Create a copy of the context and run the decorated function within that so changes to
        # the child context don't affect the parent context.
        def _decorator_parent_ctx(*args, **kwargs):
            def _decorator_in_child_ctx():
                self._push()
                try:
                    return self._fn(*args, **kwargs)
                finally:
                    self._pop()

            return copy_context().run(_decorator_in_child_ctx)

        return _decorator_parent_ctx

    def create_decorator(self):
        if asyncio.iscoroutinefunction(self._fn):
            return self._create_decorator_async()
        else:
            return self._create_decorator()


def with_new_correlation_context(f):
    return CorrelationContextDecorator(f).create_decorator()

def add_correlation_fields(log_record):
    stack = correlation_id.get()
    log_record.correlation_id = ",".join(stack)
    # I'm not sure why, but JournalHandler doesn't send these off unless there uppercase.
    log_record.__dict__['CORRELATION_ID'] = log_record.correlation_id

def setup_log_record_customization():
    """
    Some black magic to add fields to the log records.
    See https://docs.python.org/3/howto/logging-cookbook.html#customizing-logrecord.
    """

    def record_factory(*args, **kwargs):
        log_record = previous_log_record_factory(*args, **kwargs)
        add_correlation_fields(log_record)
        return log_record

    previous_log_record_factory = logging.getLogRecordFactory()
    logging.setLogRecordFactory(record_factory)


def setup_logging():
    def get_console_format():
        # https://docs.python.org/3/howto/logging-cookbook.html#formatting-styles
        return (
            '[%(asctime)s]'
            '[%(correlation_id)s]'
            '[%(threadName)s]'
            '[%(levelname)s]'
            '[%(name)s]'
            '[%(filename)s:%(lineno)d]'
            ' '
            '%(message)s'
        )

    def create_console_handler():
        console_handler = StreamHandler()
        console_handler.setFormatter(Formatter(get_console_format()))
        return console_handler

    def create_file_handler(fn):
        h = FileHandler(filename=fn)
        h.setFormatter(Formatter(get_console_format()))
        return h

    setup_log_record_customization()

    root = getLogger()
    root.setLevel("DEBUG")

    root.addHandler(create_console_handler())


class MySSHClient(SSHClient):

    def connection_made(self, conn):
        logger.info('connection_made - blocking sleep for 3 seconds')
        sleep(3)

    def connection_lost(self, exc):
        logger.info('connection_lost')

@with_new_correlation_context
async def do_work():
    try:
        async with asyncssh.connect(
            host='localhost',
            port=22,
            username='root',
            password='foo',
            known_hosts=None,
            client_factory=MySSHClient
        ) as c:
            logger.info("Ready to use connection")
    except BaseException as e:
        logger.info(f"handle exception ({type(e)})")



async def _impl():
    try:
        await asyncio.wait_for(do_work(), timeout=3)
    except asyncio.exceptions.TimeoutError:
        return False
    return True


async def main():
    try:
        setup_logging()
        get_event_loop().set_debug(True)
        await gather(_impl(), _impl(), return_exceptions=False)
    except Exception:
        logger.exception("Unhandled exception")



if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(main())
