from collections import OrderedDict

from dpkt.http import Response, parse_body
from dpkt import UnpackError
from dpkt.compat import BytesIO


class CustomResponse(Response):
    __hdr_defaults__ = {"version": "1.0", "status": "200", "reason": "OK"}
    __proto = "HTTP"

    def _parse_headers_preserve_case(self, f):
        """Return dict of HTTP headers parsed from a file object."""
        d = OrderedDict()
        while 1:
            # The following logic covers two kinds of loop exit criteria.
            # 1) If the header is valid, when we reached the end of the header,
            #    f.readline() would return with '\r\n', then after strip(),
            #    we can break the loop.
            # 2) If this is a weird header, which do not ends with '\r\n',
            #    f.readline() would return with '', then after strip(),
            #    we still get an empty string, also break the loop.
            line = f.readline().strip().decode("ascii", "ignore")
            if not line:
                break
            l_ = line.split(":", 1)
            if len(l_[0].split()) != 1:
                raise UnpackError("invalid header: %r" % line)

            # Do not perform any conversions to lowercase here
            k = l_[0]
            v = len(l_) != 1 and l_[1].lstrip() or ""
            if k in d:
                if not type(d[k]) is list:
                    d[k] = [d[k]]
                d[k].append(v)
            else:
                d[k] = v
        return d

    def unpack(self, buf):
        f = BytesIO(buf)
        line = f.readline()
        l_ = line.strip().decode("ascii", "ignore").split(None, 2)
        if len(l_) < 2 or not l_[0].startswith(self.__proto) or not l_[1].isdigit():
            raise UnpackError("invalid response: %r" % line)
        self.version = l_[0][len(self.__proto) + 1 :]
        self.status = l_[1]
        self.reason = l_[2] if len(l_) > 2 else ""
        # RFC Sec 4.3.
        # http://www.w3.org/Protocols/rfc2616/rfc2616-sec4.html#sec4.3.
        # For response messages, whether or not a message-body is included with
        # a message is dependent on both the request method and the response
        # status code (section 6.1.1). All responses to the HEAD request method
        # MUST NOT include a message-body, even though the presence of entity-
        # header fields might lead one to believe they do. All 1xx
        # (informational), 204 (no content), and 304 (not modified) responses
        # MUST NOT include a message-body. All other responses do include a
        # message-body, although it MAY be of zero length.
        is_body_allowed = int(self.status) >= 200 and 204 != int(self.status) != 304

        f = BytesIO(f.read())

        # Parse headers, preserving the case as well
        self.headers = self._parse_headers_preserve_case(f)
        headers_lowercase = {k.lower(): v for k, v in self.headers.items()}

        # Parse body
        if is_body_allowed:
            self.body = parse_body(f, headers_lowercase)
        else:
            self.body = b""
        # Save the rest
        self.data = f.read()
