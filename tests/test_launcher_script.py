from pathlib import Path
import unittest


class LauncherScriptTests(unittest.TestCase):
    def test_bat_creates_venv_installs_requirements_and_forwards_args(self):
        script = Path("webui-user.bat").read_text(encoding="utf-8").lower()

        self.assertIn("cd /d \"%~dp0\"", script)
        self.assertIn("enabledelayedexpansion", script)
        self.assertIn("python.exe", script)
        self.assertIn("!base_python! -m venv", script)
        self.assertIn("-m pip install -r requirements.txt", script)
        self.assertIn("-m app web", script)
        self.assertIn("%*", script)


if __name__ == "__main__":
    unittest.main()
