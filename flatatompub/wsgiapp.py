import os
from flatatompub import flatapp
from flatatompub.store import Store
from flatatompub.dec import bindery
from taggerclient import atom
import pkg_resources

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
    feed_title=None,
    index='FlatAtomPub:simple',
    **kwargs):
    index_factory = load_entry_point('flatatompub.index_factory', index)
    index_global_conf = global_conf.copy()
    index_global_conf.update(kwargs)
    index_global_conf.update(dict(
        debug=debug,
        clear=clear,
        page_limit=page_limit,
        feed_info=feed_info,
        feed_title=feed_title))
    index_options = {}
    for name, value in kwargs.items():
        if name.startswith('index'):
            name = name[len('index'):].strip()
            index_options[name] = value
    if kwargs:
        raise TypeError(
            "Unexpected configuration keys: %s"
            % ', '.join(kwargs.keys()))
    index = index_factory(index_global_conf, **index_options)
    from paste.deploy.converters import asbool
    data_dir = os.path.normpath(data_dir)
    page_limit = int(page_limit)
    store = Store(data_dir, index=index)
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


def load_entry_point(group, name):
    if ':' not in name:
        dist, ep_name = name, 'main'
    else:
        dist, ep_name = name.split(':', 1)
    return pkg_resources.load_entry_point(dist, group, ep_name)
