import os
import re
from pysqlite2.dbapi2 import connect
from flatatompub import naiveindex
from taggerclient.atom import tostring
from taggerclient import gdata
from lxml.etree import XPath
import textwrap
import atexit
import threading

def as_string(obj):
    if obj is None:
        return ''
    else:
        return _as_string(obj)
    
_as_string = XPath('string()')

def db_date(dt):
    if dt is None:
        return None
    else:
        return dt.strftime('%Y-%m-%dT%H:%M:%S')

def format_sql(msg, *args):
    if args:
        msg = msg.replace('?', '%r')
        msg = msg % args[0]
    msg = textwrap.dedent(msg)
    msg = ['    %s' % line
           for line in msg.splitlines()
           if line.strip()]
    msg = '\n'.join(msg)
    return msg

dbs = {}

def _close_dbs():
    ## FIXME: only closes in main thread
    for localobj in dbs.values():
        try:
            localobj.conn.close()
        except AttributeError:
            pass
atexit.register(_close_dbs)

class SQLiteIndex(naiveindex.Index):

    create_table_statements = [
        ('entries', """
    CREATE TABLE %(table_prefix)sentries (
        slug STRING PRIMARY KEY,
        id STRING NOT NULL,
        title STRING,
        published TIMSTAMP,
        updated TIMESTAMP,
        edited TIMESTAMP,
        content STRING,
        full_content STRING,
        author_email STRING,
        author_name STRING,
        author_uri STRING,
        author_full STRING
    )"""),
        ('categories', """
    CREATE TABLE %(table_prefix)scategories (
        entry_slug STRING NOT NULL,
        term STRING NOT NULL,
        scheme STRING,
        label STRING
    )"""),
        ('links', """
    CREATE TABLE %(table_prefix)slinks (
        entry_slug STRING NOT NULL,
        href STRING NOT NULL,
        rel STRING NOT NULL,
        type STRING,
        title STRING
    )"""),
        ]
    
    def __init__(self, db_filename, table_prefix='', debug_sql=False):
        self.db_filename = db_filename
        db_dir = os.path.dirname(db_filename)
        if not os.path.exists(db_dir):
            os.makedirs(db_dir)
        self.table_prefix = table_prefix
        self.debug_sql = debug_sql
        self.create_database()

    def table_exists(self, table_name):
        cur = self.execute("""
        SELECT tbl_name FROM sqlite_master
        WHERE type='table' AND tbl_name = '%(table_prefix)s%(table_name)s'
        """ % dict(table_prefix=self.table_prefix, table_name=table_name, ))
        return bool(cur.fetchall())

    @property
    def conn(self):
        try:
            localobj = dbs[self.db_filename]
        except KeyError:
            localobj = dbs[self.db_filename] = threading.local()
        try:
            conn = localobj.conn
        except AttributeError:
            localobj.conn = conn = connect(self.db_filename, isolation_level=None)
        return conn

    def execute(self, sql, *args):
        if self.debug_sql:
            print format_sql(sql, *args)
        cur = self.conn.cursor()
        cur.execute(sql, *args)
        if sql.upper().strip().startswith('SELECT'):
            return cur
        else:
            cur.close()
            return None

    def create_database(self):
        for table_name, sql in self.create_table_statements:
            if not self.table_exists(table_name):
                self.execute(sql % dict(table_prefix=self.table_prefix))

    def rewrite_entry(self, slug, entry):
        return entry

    def entry_added(self, slug, entry):
        self.execute("""
        INSERT INTO %sentries (
          slug,
          id,
          title,
          published,
          updated,
          edited,
          content,
          full_content,
          author_email,
          author_name,
          author_uri,
          author_full)
        VALUES (
          ?,
          ?,
          ?,
          ?,
          ?,
          ?,
          ?,
          ?,
          ?,
          ?,
          ?,
          ?
        )""" % self.table_prefix, (
            slug,
            entry.id,
            entry.title,
            db_date(entry.published),
            db_date(entry.updated),
            db_date(entry.edited),
            as_string(entry.find('content')),
            as_string(entry),
            entry.author and entry.author.email,
            entry.author and entry.author.name,
            entry.author and entry.author.uri,
            as_string(entry.author)))
        for cat in entry.categories:
            self.execute("""
            INSERT INTO %scategories (
              entry_slug,
              term,
              scheme,
              label)
            VALUES (
              ?,
              ?,
              ?,
              ?
            )""" % self.table_prefix, (
                slug,
                cat.term,
                cat.scheme,
                cat.label))
        for link in entry.rel_links(None):
            self.execute("""
            INSERT INTO %slinks (
              entry_slug,
              href,
              rel,
              type,
              title)
            VALUES (
              ?,
              ?,
              ?,
              ?,
              ?
            )""" % self.table_prefix, (
                slug,
                link.href,
                link.rel or 'alternate',
                link.type,
                link.title))

    def entry_updated(self, slug, entry):
        self.entry_deleted(slug, entry)
        self.entry_added(slug, entry)

    def entry_deleted(self, slug, entry):
        self.execute("""
        DELETE FROM %sentries WHERE slug = ?""" % self.table_prefix, (slug,))
        self.execute("""
        DELETE FROM %scategories WHERE entry_slug = ?""" % self.table_prefix, (slug,))
        self.execute("""
        DELETE FROM %slinks WHERE entry_slug = ?""" % self.table_prefix, (slug,))

    def clear(self):
        for table in ['entries', 'categories', 'links']:
            self.execute("DELETE FROM %s%s" % (self.table_prefix, table))

    def gdata_query(self, gdata, store):
        items = []
        arguments = []
        if gdata.q:
            sql, arg = self.like_query('full_content', gdata.q)
            items.append(sql)
            arguments.append(arg)
            gdata.q = None
        if gdata.author:
            sql, arg = self.like_query('author_full', gdata.author)
            items.append(sql)
            arguments.append(arg)
            gdata.author = None
        for query, column in [(gdata.updated, 'updated'),
                              (gdata.published, 'published')]:
            if query:
                if query[0]:
                    items.append('date(%s) >= date(?)' % db_date(column))
                    arguments.append(query[0])
                if query[1]:
                    items.append('date(%s) <= date(?)' % db_date(column))
                    arguments.append(query[1])
        gdata.updated = gdata.published = None
        if gdata.category_query:
            item, args = self.category_query(gdata.category_query)
            items.append(item)
            arguments.extend(args)
            gdata.cateogry_query = None
        if gdata.rels:
            for rel_name, href in gdata.rels.items():
                items.append("""
                EXISTS (SELECT %(table_prefix)slinks.entry_slug FROM %(table_prefix)slinks
                        WHERE (%(table_prefix)slinks.entry_slug = %(table_prefix)sentries.slug
                               AND %(table_prefix)slinks.rel = ?
                               AND %(table_prefix)slinks.href = ?))
                """ % dict(table_prefix=self.table_prefix))
                arguments.extend([rel_name, href])
            gdata.rels = {}
        if len(items) > 1:
            items = ['(%s)' % i for i in items]
        if not items:
            items = ['1=1']
        sql = """
        SELECT %(table_prefix)sentries.slug
        FROM %(table_prefix)sentries
        WHERE %(query)s
        """ % dict(table_prefix=self.table_prefix,
                   query=' AND '.join(items))
        cur = self.execute(sql, tuple(arguments))
        slugs = [row[0] for row in cur.fetchall()]
        cur.close()
        return (gdata, slugs)

    def like_query(self, column, pattern):
        if pattern.lower() == pattern:
            return ('%s LIKE ?' % column), '%' + pattern.replace('%', '%%') + '%'
        else:
            ## FIXME: escape *
            return ('%s GLOB ?' % column), '*' + pattern + '*'

    def category_query(self, query):
        if isinstance(query, gdata.NOT):
            item, args = self.category_query(query.expr)
            return ('NOT %s' % item), args
        elif isinstance(query, (gdata.AND, gdata.OR)):
            if isinstance(query, gdata.AND):
                op = ' AND '
            else:
                op = ' OR '
            items = []
            all_args = []
            for expr in query:
                item, args = self.category_query(expr)
                items.append(item)
                all_args.extend(args)
            if len(items) > 1:
                items = ['(%s)' % i for i in items]
            return op.join(items), all_args
        elif isinstance(query, gdata.Category):
            if query.scheme is None:
                sql = """
                EXISTS (SELECT %(table_prefix)scategories.entry_slug FROM %(table_prefix)scategories
                        WHERE (%(table_prefix)scategories.entry_slug = %(table_prefix)sentries.slug
                               AND %(table_prefix)scategories.term = ?))
                """ % dict(table_prefix=self.table_prefix)
                return sql, (query.term,)
            elif not query.scheme:
                sql = """
                EXISTS (SELECT %(table_prefix)scategories.entry_slug FROM %(table_prefix)scategories
                        WHERE (%(table_prefix)scategories.entry_slug = %(table_prefix)sentries.slug
                               AND %(table_prefix)scategories.term = ?
                               AND (%(table_prefix)scategories.scheme IS NULL
                                    or %(table_prefix)scategories.scheme = '')))
                """ % dict(table_prefix=self.table_prefix)
                return sql, (query.term,)
            else:
                sql = """
                EXISTS (SELECT %(table_prefix)scategories.entry_slug FROM %(table_prefix)scategories
                        WHERE (%(table_prefix)scategories.entry_slug = %(table_prefix)sentries.slug
                               AND %(table_prefix)scategories.term = ?
                               AND %(table_prefix)scategories.scheme = ?))
                """ % dict(table_prefix=self.table_prefix)
                return sql, (query.term, query.scheme)
        else:
            assert 0, (
                "Unknown category query type: %r" % query)

    def most_recent(self, store, start_index, length):
        if length is None:
            length_sql = ""
            args = (start_index,)
        else:
            length_sql = "LIMIT ?"
            args = (length, start_index)
        cur = self.execute('SELECT COUNT(*) FROM %sentries' % self.table_prefix)
        total_length = cur.fetchone()[0]
        cur.close()
        sql = """
        SELECT %(table_prefix)sentries.slug
        FROM %(table_prefix)sentries
        ORDER BY %(table_prefix)sentries.edited DESC
        %(length_sql)s
        OFFSET ?
        """ % dict(table_prefix=self.table_prefix,
                   length_sql=length_sql)
        cur = self.execute(sql, args)
        slugs = [row[0] for row in cur.fetchall()]
        cur.close()
        return (None, slugs)
            
def make_index(global_conf, db=None, debug=False, table_prefix=''):
    from paste.deploy.converters import asbool
    if db is None:
        db = global_conf.get('db')
        if db is None:
            ## FIXME: make sure db.sqlite can't be served:
            db = os.path.join(global_conf['data_dir'], 'db/db.sqlite')
    return SQLiteIndex(db, table_prefix=table_prefix,
                       debug_sql=asbool(debug))
