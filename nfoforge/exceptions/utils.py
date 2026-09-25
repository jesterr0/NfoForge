from traceback import format_exception


def get_full_traceback(exception: Exception) -> str:
    """Generates caught traceback errors in their original format"""
    return "".join(format_exception(exception)).rstrip()
