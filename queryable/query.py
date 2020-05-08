import uuid
from collections import Counter
from pprint import pformat

from .boolean import Boolean, eq, pred, TRUE

__all__ = [
    "CollectionBase",
    "convert",
    "Dict",
    "List",
    "NONE",
    "Queryable",
    "WhereQuery",
    "q"
]

NONE = object()


class CollectionBase:
    def __init__(self, data=None, parents=None):
        super().__init__(data or [])
        self.parents = parents or []
        self.uid = uuid.uuid4()

    # hash and eq are defined so we can deduplicate as we chase down data
    # structure roots.
    def __hash__(self):
        return hash(self.uid)

    def __eq__(self, other):
        try:
            return self.uid == other.uid
        except:
            return False


class List(CollectionBase, list):
    """ A list that remembers the data structure to which it belongs. """
    pass


class Dict(CollectionBase, dict):
    """ A dict that remembers the data structure to which it belongs. """
    pass


def _desugar_part(x):
    if isinstance(x, Boolean):
        return x
    if callable(x):
        return pred(x)
    return eq(x)


def get_roots(data):
    results = List()
    seen = set()

    def inner(d):
        if not d.parents and d not in seen:
            results.append(d)
            seen.add(d)
        else:
            for p in d.parents:
                if p not in seen:
                    inner(p)
                seen.add(p)

    if data.parents:
        inner(data)
    return results


class _Queryable:
    __slots__ = ["value"]

    def __init__(self, value):
        self.value = value

    def keys(self):
        keys = []
        seen = set()

        def inner(val):
            if isinstance(val, Dict):
                new = val.keys() - seen
                keys.extend(new)
                seen.update(new)

            if isinstance(val, List):
                for i in val:
                    try:
                        new = i.keys() - seen
                        keys.extend(new)
                        seen.update(new)
                    except:
                        inner(i)

        inner(self.value)
        return sorted(set(keys))

    def most_common(self, top=None):
        return Counter(self.value).most_common(top)

    def unique(self):
        return sorted(set(self.value))

    def sum(self):
        return sum(self.value)

    def to_dataframe(self):
        import pandas
        return pandas.DataFrame(self.value)

    @property
    def parents(self):
        gp = []
        seen = set()
        for p in self.value.parents:
            for g in p.parents:
                if g not in seen:
                    gp.append(g)
                    seen.add(g)
        return _Queryable(List(self.value.parents, parents=gp))

    @property
    def roots(self):
        return _Queryable(get_roots(self.value))

    def upto(self, query):
        cur = self
        while cur:
            p = cur.parents
            if p.parents[query]:
                if p.value and isinstance(p.value[0], list):
                    return cur
                else:
                    return p
            cur = p

    def find(self, *args):
        results = List()
        queries = [self._desugar(a) for a in args]

        def run_queries(node):
            n = node
            for q in queries:
                n = n._handle_child_query(q)

            if n.value:
                results.extend(n.value)
                results.parents.extend(n.value.parents)

            if isinstance(node.value, Dict):
                for i in node.value.values():
                    if isinstance(i, CollectionBase):
                        run_queries(_Queryable(i))
            elif isinstance(node.value, List):
                for i in node.value:
                    if isinstance(i, CollectionBase):
                        run_queries(_Queryable(i))
        run_queries(self)
        return _Queryable(results)

    def __getattr__(self, key):
        # allow dot traversal for simple key names.
        return self.__getitem__(key)

    def __dir__(self):
        # jedi in doesn't tab complete when __getattr__ is defined b/c it could
        # execute arbitrary code. So.. throw caution to the wind.

        # import IPython
        # from traitlets.config.loader import Config

        # IPython.core.completer.Completer.use_jedi = False
        # c = Config()
        # IPython.start_ipython([], user_ns=locals(), config=c)
        return self.get_keys()

    def __len__(self):
        return len(self.value)

    def __bool__(self):
        return bool(self.value)

    def __iter__(self):
        for i in self.value:
            yield _Queryable(i)

    def _handle_child_query(self, query):

        def inner(val):
            if isinstance(val, Dict):
                r = query(val)
                if r:
                    return List(r, parents=[val])
                return List()

            elif isinstance(val, List):
                results = List()
                for i in val:
                    r = inner(i) if isinstance(i, List) else query(i)
                    if r:
                        results.parents.append(i)
                        results.extend(r)
                return results
            return List()

        return _Queryable(inner(self.value))

    def _desugar_tuple_query(self, key):
        value = self.value
        name_part, value_part = key
        value_query = _desugar_part(value_part) if value is not NONE else TRUE

        if name_part is NONE:
            def query(val):
                results = []
                try:
                    for v in val.values():
                        if isinstance(v, list):
                            results.extend(v)
                        else:
                            results.append(v)
                except:
                    return []
                return results
        elif not callable(name_part):
            def query(val):
                try:
                    v = val[name_part]
                    if value_query.test(v):
                        return v if isinstance(v, list) else [v]
                except:
                    return []
        else:
            name_query = _desugar_part(name_part)

            def query(val):
                results = []
                try:
                    for k, v in val.items():
                        if name_query.test(k) and value_query.test(v):
                            if isinstance(v, list):
                                results.extend(v)
                            else:
                                results.append(v)
                except:
                    return []
                return results

        return query

    def _desugar_name_query(self, key):
        if key is NONE:
            def query(val):
                results = []
                try:
                    for v in val.values():
                        if isinstance(v, list):
                            results.extend(v)
                        else:
                            results.append(v)
                except:
                    return []
                return results
        elif not callable(key):
            def query(val):
                try:
                    r = val[key]
                    return r if isinstance(r, list) else [r]
                except:
                    return []
        else:
            name_query = _desugar_part(key)

            def query(val):
                results = []
                try:
                    for k, v in val.items():
                        if name_query.test(k):
                            if isinstance(v, list):
                                results.extend(v)
                            else:
                                results.append(v)
                except:
                    return []
                return results

        return query

    def _desugar(self, key):
        if isinstance(key, tuple):
            return self._desugar_tuple_query(key)
        return self._desugar_name_query(key)

    def __getitem__(self, key):
        query = self._desugar(key)
        return self._handle_child_query(query)

    def _handle_where_query(self, query):
        seen = set()

        def inner(val):
            results = List()
            for i in val:
                if isinstance(i, List):
                    r = inner(i)
                    if r:
                        results.append(i)
                        for p in i.parents:
                            if p not in seen:
                                results.parents.append(p)
                                seen.add(p)
                elif query(i):
                    results.append(i)
                    for p in i.parents:
                        if p not in seen:
                            results.parents.append(p)
                            seen.add(p)
            return results

        return _Queryable(inner(self.value))

    def where(self, query, value=NONE):
        """
        Accepts WhereQuery instances, combinations of WhereQuery instances, or
        a callable that will be passed a Queryable version of each item. Where
        queries only make sense against lists.
        """

        # if value is defined, the caller didn't bother to make a WhereQuery
        if value is not NONE:
            query = WhereQuery(query, value)

            def runquery(val):
                return query.test(val)

        # query already contains WhereQuery instances. We check for Boolean
        # because query might some combination of WhereQuerys.
        elif isinstance(query, Boolean):
            def runquery(val):
                return query.test(val)

        # value is not defined, and query is not a WhereQuery. If query is a
        # callable, it's just a regular function or lambda. We assume the
        # caller wants to manually inspect each item.
        elif callable(query):
            def runquery(val):
                return query(_Queryable(val))

        # this handles the case where the caller wants to simply check for the
        # existence of a key without needing to construct a WhereQuery. Because
        # of the above checks, query here can be only a primitive value.
        else:
            query = WhereQuery(query)

            def runquery(val):
                return query.test(val)

        return self._handle_where_query(runquery)

    def __repr__(self):
        return f"_Queryable({pformat(self.value)})"


class WhereQuery(Boolean):
    """ Only use in where queries. """
    def __init__(self, name_part, value_part=NONE):
        value_query = _desugar_part(value_part) if value_part is not NONE else TRUE

        if name_part is NONE:
            self.query = lambda val: any(value_query.test(v) for v in val.values())
        elif not callable(name_part):
            self.query = lambda val: value_query.test(val[name_part]) if name_part in val else False
        else:
            name_query = _desugar_part(name_part)
            self.query = lambda val: any(name_query.test(k) and value_query.test(v) for k, v in val.items())

    def test(self, value):
        try:
            return self.query(value)
        except:
            return False


q = WhereQuery


def convert(data, parent=None):
    """
    Convert nest of dicts and lists into Dicts and Lists that contain
    pointers to their parents.
    """
    if isinstance(data, dict):
        d = Dict(parents=[parent] if parent is not None else [])
        d.update({k: convert(v, parent=d) for k, v in data.items()})
        return d

    if isinstance(data, list):
        l = List(parents=[parent] if parent is not None else [])
        l.extend(convert(i, parent=l) for i in data)
        return l

    return data


def Queryable(data):
    if isinstance(data, _Queryable):
        return data

    if isinstance(data, CollectionBase):
        return _Queryable(data)

    return _Queryable(convert(data))