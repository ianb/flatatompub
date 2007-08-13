from decorator import decorator
from webob import Request, Response

class WebResponse(Response):

    default_content_type = 'text/html; utf8'

    def write(self, data):
        self.body += data

def wsgiapp(func):
    def replacement_app(environ, start_response):
        req = Request(environ)
        res = WebResponse(request=req)
        req.response = res
        result = func(req)
        add_response = None
        if result is None:
            result = res
        elif isinstance(result, Response):
            # All good
            add_response = res
        elif isinstance(result, basestring):
            res.body = result
            result = res
        else:
            # WSGI application...
            add_response = res
        if (add_response is not None
            and 'set-cookie' in add_response.headers):
            def repl_start_response(status, headers, exc_info=None):
                headers.extend(add_response.getall('Set-Cookie'))
                return start_response(status, headers, exc_info)
        else:
            repl_start_response = start_response
        return result(environ, repl_start_response)
    try:
        replacement_app.func_name = func.func_name
    except Exception, e:
        print e
    return replacement_app

def bindery(app, **kw):
    def binding_middleware(environ, start_response):
        environ.setdefault('webob.adhoc_attrs', {}).update(kw)
        return app(environ, start_response)
    return binding_middleware
