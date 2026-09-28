class ForemanError(Exception):
    pass


class NotFoundError(ForemanError):
    pass


class ConflictError(ForemanError):
    pass
