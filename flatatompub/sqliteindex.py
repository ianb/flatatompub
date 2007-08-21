import os
import re
from sqlite import Connection
from flatatompub import naiveindex
from taggerclient.atom import tostring
from taggerclient import gdata
from lxml.etree import XPath
import textwrap

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
        return dt.strftime('%Y-%m-%d %H:%M:%S')

def format_sql(msg, *args):
    msg = msg.replace('%s', '%r')
    msg = re.sub(r'(%[(].*?[)])s', r'\1r', msg)
    if args:
        msg = msg % args[0]
    msg = textwrap.dedent(msg)
    msg = ['    %s' % line
           for line in msg.splitlines()
           if line.strip()]
    msg = '\n'.join(msg)
    return msg

class SQLiteIndex(naiveindex.Index):

    CREATE_ENTRIES = """
    CREATE TABLE entries (
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
    )"""
    CREATE_CATEGORIES = """
    CREATE TABLE categories (
        entry_slug STRING NOT NULL,
        term STRING NOT NULL,
        scheme STRING,
        label STRING
    )"""
    CREATE_LINKS = """
    CREATE TABLE links (
        entry_slug STRING NOT NULL,
        href STRING NOT NULL,
        rel STRING NOT NULL,
        type STRING,
        title STRING
    )"""
    

    def __init__(self, db_filename, debug_sql=False):
        self.db_filename = db_filename
        self.debug_sql = debug_sql
        exists = os.path.exists(db_filename)
        self.conn = Connection(db_filename, encoding='utf8')
        if not exists:
            self.create_database()
        cur = self.execute("SELECT tbl_name FROM sqlite_master WHERE type='table' and tbl_name = 'entries'")
        rows = cur.fetchall()
        if not rows:
            self.create_database()

    def execute(self, sql, *args):
        if self.debug_sql:
            print format_sql(sql, *args)
        cur = self.conn.cursor()
        cur.execute(sql, *args)
        return cur

    def create_database(self):
        for sql in self.CREATE_ENTRIES, self.CREATE_CATEGORIES, self.CREATE_LINKS:
            self.execute(sql)

    def rewrite_entry(self, slug, entry):
        return entry

    def entry_added(self, slug, entry):
        self.execute("""
        INSERT INTO entries (
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
          %(slug)s,
          %(id)s,
          %(title)s,
          %(published)s,
          %(updated)s,
          %(edited)s,
          %(content)s,
          %(full_content)s,
          %(author_email)s,
          %(author_name)s,
          %(author_uri)s,
          %(author_full)s
        )""", dict(
            slug=slug,
            id=entry.id,
            title=entry.title,
            published=db_date(entry.published),
            updated=db_date(entry.updated),
            edited=db_date(entry.edited),
            content=as_string(entry.find('content')),
            full_content=as_string(entry),
            author_email=entry.author and entry.author.email,
            author_name=entry.author and entry.author.name,
            author_uri=entry.author and entry.author.uri,
            author_full=as_string(entry.author)))
        for cat in entry.categories:
            self.execute("""
            INSERT INTO categories (
              entry_slug,
              term,
              scheme,
              label)
            VALUES (
              %(entry_slug)s,
              %(term)s,
              %(scheme)s,
              %(label)s
            )""", dict(
                entry_slug=slug,
                term=cat.term,
                scheme=cat.scheme,
                label=cat.label))
        for link in entry.rel_links(None):
            self.execute("""
            INSERT INTO links (
              entry_slug,
              href,
              rel,
              type,
              title)
            VALUES (
              %(entry_slug)s,
              %(href)s,
              %(rel)s,
              %(type)s,
              %(title)s
            )""", dict(
                entry_slug=slug,
                href=link.href,
                rel=link.rel or 'alternate',
                type=link.type,
                title=link.title))

    def entry_updated(self, slug, entry):
        self.entry_deleted(slug, entry)
        self.entry_added(slug, entry)

    def entry_deleted(self, slug, entry):
        self.execute("""
        DELETE FROM entries WHERE slug = %s""", (slug,))
        self.execute("""
        DELETE FROM categories WHERE entry_slug = %s""", (slug,))
        self.execute("""
        DELETE FROM links WHERE entry_slug = %s""", (slug,))

    def clear(self):
        for table in ['entries', 'categories', 'links']:
            self.execute("DELETE FROM %s" % table)

    def gdata_query(self, gdata, store):
        items = []
        arguments = []
        if gdata.q:
            items.append('full_content ILIKE %s')
            arguments.append('%' + gdata.q.replace('%', '%%') + '%')
            gdata.q = None
        if gdata.author:
            items.append('author_full ILIKE %s')
            arguments.append('%' + gdata.author.replace('%', '%%') + '%')
            gdata.author = None
        for query, column in [(gdata.updated, 'updated'),
                              (gdata.published, 'published')]:
            if query:
                if query[0]:
                    items.append('%s >= %%s' % column)
                    arguments.append(query[0])
                if query[1]:
                    items.append('%s <= %%s' % column)
                    arguments.append(query[1])
        gdata.updated = gdata.published = None
        if gdata.category_query:
            item, args = self.category_query(gdata.catalog_query)
            items.append(item)
            arguments.extend(args)
            gdata.cateogry_query = None
        sql = """
        SELECT entries.slug
        FROM entries
        WHERE %s
        """ % ' AND '.join(['(%s)' % i for i in items])
        cur = self.execute(sql, tuple(arguments))
        slugs = [row[0] for row in cur.fetchall()]
        return (gdata, slugs)

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
                items.append('(%s)' % item)
                all_args.extend(args)
            return op.join(items), all_args
        elif isinstance(query, gdata.Category):
            if query.scheme is None:
                sql = """
                EXISTS(SELECT * FROM categories
                       WHERE (categories.entry_slug = entries.slug
                              AND categories.term = %s))
                """
                return sql, (query.term,)
            else:
                sql = """
                EXISTS(SELECT * FROM categories
                       WHERE (categories.entry_slug = entries.slug
                              AND categories.term = %s
                              AND categories.scheme = %s))
                """
                return sql, (query.term, query.scheme)
        else:
            assert 0, (
                "Unknown category query type: %r" % query)

    def most_recent(self, store, start_index, length):
        if length is None:
            length_sql = ""
            args = (start_index,)
        else:
            length_sql = "LIMIT %s"
            args = (length, start_index)
        cur = self.execute('SELECT COUNT(*) FROM entries')
        total_length = cur.fetchone()[0]
        sql = """
        SELECT entries.slug
        FROM entries
        ORDER BY entries.edited DESC
        %s
        OFFSET %%s
        """ % length_sql
        cur = self.execute(sql, args)
        slugs = [row[0] for row in cur.fetchall()]
        return (None, slugs)
            
def make_index(global_conf, db=None, debug=False):
    from paste.deploy.converters import asbool
    if db is None:
        db = global_conf.get('db')
        if db is None:
            ## FIXME: make sure db.sqlite can't be served:
            db = os.path.join(global_conf['data_dir'], 'db.sqlite')
    return SQLiteIndex(db, debug_sql=asbool(debug))
