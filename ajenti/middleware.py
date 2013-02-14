import hashlib
import time
import Cookie
import random
import gevent

import ajenti
from ajenti.api import *
from ajenti.http import HttpHandler
from ajenti.users import UserManager


class Session:
    """
    Holds the HTTP session data
    """

    def __init__(self, id):
        self.touch()
        self.id = id
        self.data = {}
        self.active = True
        self.greenlets = []

    def destroy(self):
        """
        Marks this session as dead
        """
        self.active = False
        for g in self.greenlets:
            g.kill()

    def touch(self):
        """
        Updates the "last used" timestamp
        """
        self.timestamp = time.time()

    def spawn(self, *args, **kwargs):
        """
        Spawns a ``greenlet`` that will be stopped and garbage-collected when the session is destroyed

        :params: Same as for :func:`gevent.spawn`
        """
        g = gevent.spawn(*args, **kwargs)
        self.greenlets += [g]

    def is_dead(self):
        return not self.active or (time.time() - self.timestamp) > 3600

    def set_cookie(self, context):
        """
        Adds headers to :class:`ajenti.http.HttpContext` that set the session cookie
        """
        C = Cookie.SimpleCookie()
        C['session'] = self.id
        C['session']['path'] = '/'
        context.add_header('Set-Cookie', C['session'].OutputString())


@plugin
class SessionMiddleware (HttpHandler):
    def __init__(self):
        self.sessions = {}

    def generate_session_id(self, context):
        hash = str(random.random())
        hash += context.env.get('REMOTE_ADDR', '')
        hash += context.env.get('REMOTE_HOST', '')
        hash += context.env.get('HTTP_USER_AGENT', '')
        hash += context.env.get('HTTP_HOST', '')
        return hashlib.sha1(hash).hexdigest()

    def vacuum(self):
        """
        Eliminates dead sessions
        """
        for session in [x for x in self.sessions.values() if x.is_dead()]:
            del self.sessions[session.id]

    def open_session(self, context):
        """
        Creates a new session for the :class:`ajenti.http.HttpContext`
        """
        session_id = self.generate_session_id(context)
        session = Session(session_id)
        self.sessions[session_id] = session
        return session

    def handle(self, context):
        self.vacuum()
        cookie_str = context.env.get('HTTP_COOKIE')
        # fix bad cookies
        if cookie_str:
            cookie_str = cookie_str.replace('&', '_')

        cookie = Cookie.SimpleCookie(cookie_str).get('session')
        context.session = None
        if cookie is not None and cookie.value in self.sessions:
            # Session found
            context.session = self.sessions[cookie.value]
            if context.session.is_dead():
                context.session = None
        if context.session is None:
            context.session = self.open_session(context)
        context.session.set_cookie(context)
        context.session.touch()


@plugin
class AuthenticationMiddleware (HttpHandler):
    def handle(self, context):
        if not hasattr(context.session, 'identity'):
            if ajenti.config.tree.authentication:
                context.session.identity = None
            else:
                context.session.identity = 'root'
                context.session.appcontext = AppContext(context)

    def try_login(self, context, username, password):
        if UserManager.get().check_password(username, password):
            context.session.identity = username
            context.session.appcontext = AppContext(context)
            return True
        return False

    def logout(self, context):
        context.session.identity = None


__all__ = ['Session', 'SessionMiddleware', 'AuthenticationMiddleware']