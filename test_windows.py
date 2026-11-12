import unittest
from pathlib import Path
from desktop_workspace import default_app_root

class PlatformPaths(unittest.TestCase):
    def test_windows_uses_local_app_data(self):
        self.assertEqual(default_app_root('win32', {'LOCALAPPDATA':'/local'},Path('/home')),Path('/local/ONVIF Spec Review'))
    def test_windows_fallback(self):
        self.assertEqual(default_app_root('win32',{},Path('/home')),Path('/home/AppData/Local/ONVIF Spec Review'))
    def test_mac_path_remains_compatible(self):
        self.assertEqual(default_app_root('darwin',{},Path('/home')),Path('/home/Library/Application Support/ONVIF Spec Review'))
