__author__ = "Ondieki"
__email__ = "ondieki.codes@gmail.com"

import winreg


SPEEDY = 1


def file_type(ext: str):
    """ `ext` like '.py' """

    if not ext:
        return "File"
    if SPEEDY:
        return f"{ext.strip('.').upper()} File"
    try:
        file_class = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, ext)
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, file_class) as file_type_key:
            file_type = winreg.QueryValueEx(file_type_key, "")
            default = file_type[0]
    except Exception:
        default = f"{ext.strip('.').upper()} File"
    return default
