"""
Launch long-running async tasks on dedicated background event loops.

This is the core mechanism of the background package: start_event_loop() runs
an async function forever in its own asyncio loop on a daemon thread, and
registers it with TaskMonitor for observability. Typically called at startup
(e.g. from an AppConfig.ready()).
"""
import asyncio
import threading
from threading import Thread

from .task_monitor import TaskMonitor


def start_event_loop( task_function, pass_event_loop = False ):
    """
    Start a daemon thread running an async task in its own event loop.

    :param task_function: Async function to be executed inside the thread.
    :param pass_event_loop: If True, the background loop is passed to
        task_function as its sole argument.
    """
    # Generate a name for this background task
    task_name = getattr(task_function, '__name__', str(task_function))
    if hasattr(task_function, '__self__'):
        # This is a method, include the class name
        class_name = task_function.__self__.__class__.__name__
        task_name = f"{class_name}.{task_name}"

    def run_background_task_in_thread():
        background_loop = asyncio.new_event_loop()
        asyncio.set_event_loop( background_loop )

        # Register this task for monitoring
        current_thread = threading.current_thread()
        current_thread.name = f"Background-{task_name}"
        TaskMonitor.register_task( task_name, background_loop, current_thread )

        async def run_background_task():
            if pass_event_loop:
                await task_function( background_loop )
            else:
                await task_function()
            return

        background_loop.call_soon_threadsafe( asyncio.create_task, run_background_task() )
        background_loop.run_forever()
        return

    background_thread = Thread( target = run_background_task_in_thread )
    background_thread.daemon = True
    background_thread.start()
    return
