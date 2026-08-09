class ImproperProcessException(Exception):
    _prefix = ["EXCEPTION"]

    def __init__(self, message):
        message = "%s %s" % (ImproperProcessException._prefix, message)
        super(ImproperProcessException, self).__init__(message)

