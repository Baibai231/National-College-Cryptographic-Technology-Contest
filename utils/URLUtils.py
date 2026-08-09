#!/usr/bin/python

import urllib.parse
import tldextract as tld


class URLUtils(object):
    """ Get the given URL 's domain (subdomains included)
    """

    @classmethod
    def get_domain(cls, url, strip_www=False, strip_port=True):
        if url is None:
            return None
        domain = urllib.parse.urlparse(url).netloc
        domain = domain.split(":")[0] if strip_port else domain
        return domain if not strip_www else domain.replace("www.", "")

    @classmethod
    def get_main_domain(cls, url, suffix=False):
        if url is None:
            return None
        ret = tld.extract(url)
        return ret.domain if not suffix else ret.domain + "." + ret.suffix

    @classmethod
    def get_full_domain(cls, url):
        if url is None:
            return None
        ret = tld.extract(url)
        if ret.subdomain:
            return "%s.%s.%s" % (ret.subdomain, ret.domain, ret.suffix)
        else:
            return "%s.%s" % (ret.domain, ret.suffix)

    @classmethod
    def get_subdomain(cls, url):
        if url is None:
            return None
        ret = tld.extract(url)
        return ret.subdomain

    @classmethod
    def get_path(cls, url, full_path=False):
        if url is None:
            return None
        path = urllib.parse.urlparse(url).path
        return path if not full_path else "%s?%s" % (path, cls.get_query(url))

    @classmethod
    def get_query(cls, url):
        return urllib.parse.urlparse(url).query if url else None

    @classmethod
    def get_scheme(cls, url):
        return urllib.parse.urlparse(url).scheme if url else None

    @classmethod
    def join(cls, domain: str, path: str):
        return "%s%s" % (domain, path) if domain.endswith("/") or path.startswith("/") else "%s/%s" % (domain, path)

    @classmethod
    def join_scheme(cls, scheme: str, url: str):
        return scheme + "://" + url

    @classmethod
    def strip_scheme(cls, url: str):
        if url is None:
            return None
        scheme = cls.get_scheme(url)
        return url.replace(scheme + "://", "")

    @classmethod
    def main_url(cls, url: str):
        domain = cls.get_domain(url)
        path = cls.get_path(url)
        scheme = cls.get_scheme(url)
        return URLUtils.join_scheme(scheme, cls.join(domain, path))


if __name__ == '__main__':
    url = "https://www.asjas.com:80/dakjejea.php"
    print(URLUtils.get_domain(url, strip_www=True))
