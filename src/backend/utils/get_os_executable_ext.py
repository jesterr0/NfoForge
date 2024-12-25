import platform


def get_executable_string_by_os():
    """Check executable type based on operating system"""
    operating_system = platform.system()
    if operating_system == "Windows":
        return ".exe"
    elif operating_system == "Linux":
        return ""
