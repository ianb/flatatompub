import os
from flatatompub import flatapp
from flatatompub.store import Store
from flatatompub.dec import bindery
from taggerclient import atom

class Config(object):
    def __init__(self, **kw):
        for name, value in kw.iteritems():
            setattr(self, name, value)

def make_app(
    global_conf,
    data_dir,
    debug=False,
    clear=False,
    page_limit=10,
    feed_info=None,
    feed_title=None):
    from paste.deploy.converters import asbool
    data_dir = os.path.normpath(data_dir)
    page_limit = int(page_limit)
    store = Store(data_dir)
    if asbool(clear):
        print 'Clearing store at %s' % data_dir
        store.clear()
    app = flatapp.app
    if feed_info:
        feed_info = atom.ATOM('<feed xmlns="%s">%s</feed>'
                              % (atom.atom_ns, feed_info))
    config = Config(
        page_limit=page_limit,
        feed_info=feed_info,
        feed_title=feed_title,
        )
    app = bindery(app, store=store, config=config)
    debug = asbool(debug)
    if debug:
        from paste.evalexception import EvalException
        app = EvalException(app)
    return app

