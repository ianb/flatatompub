import os
from flatatompub import flatapp
from flatatompub.store import Store
from flatatompub.dec import bindery

def make_app(
    global_conf,
    data_dir,
    debug=False,
    clear=False,
    page_limit=10):
    from paste.deploy.converters import asbool
    data_dir = os.path.normpath(data_dir)
    page_limit = int(page_limit)
    store = Store(data_dir, page_limit=page_limit)
    if asbool(clear):
        print 'Clearing store at %s' % data_dir
        store.clear()
    app = flatapp.app
    app = bindery(app, store=store)
    debug = asbool(debug)
    if debug:
        from paste.evalexception import EvalException
        app = EvalException(app)
    return app

