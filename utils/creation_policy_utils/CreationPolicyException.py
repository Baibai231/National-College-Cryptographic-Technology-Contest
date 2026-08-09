class NoAdmissiblePasswordException(Exception):
    _prefix = ["EXCEPTION"]

    def __init__(self, message):
        message = "%s %s" % (NoAdmissiblePasswordException._prefix, message)
        super(NoAdmissiblePasswordException, self).__init__(message)


class ImproperProcessException(Exception):
    _prefix = ["EXCEPTION"]

    def __init__(self, message):
        message = "%s %s" % (ImproperProcessException._prefix, message)
        super(ImproperProcessException, self).__init__(message)
