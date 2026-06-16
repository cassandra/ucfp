import asyncio
import weakref
import threading


class TaskMonitor:
    """Monitor for background event loops and tasks running in daemon threads"""
    _instances = {}  # task_function_name -> monitor info

    @classmethod
    def register_task(cls, name, loop, thread):
        """Register a background task for monitoring"""
        cls._instances[name] = {
            'loop_ref': weakref.ref(loop) if loop else None,
            'thread_ref': weakref.ref(thread) if thread else None,
            'thread_name': thread.name if thread else None,
            'registered_at': threading.current_thread().name,
        }

    @classmethod
    def get_task_status(cls):
        """Get comprehensive status of all background tasks and loops"""
        status = {
            'main_thread': {
                'name': threading.main_thread().name,
                'is_alive': threading.main_thread().is_alive(),
            },
            'current_thread': {
                'name': threading.current_thread().name,
                'active_count': threading.active_count(),
            },
            'background_tasks': {}
        }

        for task_name, info in cls._instances.items():
            task_status = {
                'registered_from': info.get('registered_at'),
                'thread_name': info.get('thread_name'),
            }

            # Check thread status
            thread = info['thread_ref']() if info['thread_ref'] else None
            task_status['thread'] = {
                'exists': thread is not None,
                'is_alive': thread.is_alive() if thread else False,
                'is_daemon': thread.daemon if thread else None,
            }

            # Check event loop status
            loop = info['loop_ref']() if info['loop_ref'] else None
            if loop:
                try:
                    # Get tasks from the background loop
                    tasks = asyncio.all_tasks(loop)
                    task_details = []

                    for task in tasks:
                        try:
                            task_info = {
                                'name': getattr(task, 'get_name', lambda: 'unnamed')(),
                                'done': task.done(),
                                'cancelled': task.cancelled(),
                            }

                            # Try to get coroutine name safely
                            try:
                                coro = task.get_coro()
                                if hasattr(coro, '__name__'):
                                    task_info['coro_name'] = coro.__name__
                                elif hasattr(coro, '__qualname__'):
                                    task_info['coro_name'] = coro.__qualname__
                                else:
                                    task_info['coro_name'] = str(type(coro).__name__)
                            except Exception:
                                task_info['coro_name'] = 'unknown'

                            task_details.append(task_info)
                        except Exception as e:
                            task_details.append({'error': f'Task info error: {e}'})

                    task_status['event_loop'] = {
                        'exists': True,
                        'is_running': loop.is_running(),
                        'is_closed': loop.is_closed(),
                        'total_tasks': len(tasks),
                        'active_tasks': len([t for t in tasks if not t.done()]),
                        'task_details': task_details,
                    }
                except Exception as e:
                    task_status['event_loop'] = {
                        'exists': True,
                        'error': f'Loop access error: {e}'
                    }
            else:
                task_status['event_loop'] = {
                    'exists': False,
                    'error': 'Event loop reference is dead'
                }

            status['background_tasks'][task_name] = task_status

        return status
