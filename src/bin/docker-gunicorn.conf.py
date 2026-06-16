def post_worker_init( worker ):
    """Start background processes after a gunicorn worker forks.

    This is the gunicorn entry point of the dual-path startup; the other is an
    app's ``AppConfig.ready()`` -> first-request signal, used by ``runserver``.
    See ``background/startup.py`` for the full rationale (launching background
    tasks at Django startup is much harder than it looks).
    """
    from background.startup import BackgroundTaskHelper
    BackgroundTaskHelper.start_background_tasks()
    return
