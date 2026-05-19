from pathlib import Path
import unittest


class DependencyTests(unittest.TestCase):
    def test_requests_is_explicit_runtime_dependency_for_gradio_import(self):
        requirements = Path("requirements.txt").read_text(encoding="utf-8").lower()
        pyproject = Path("pyproject.toml").read_text(encoding="utf-8").lower()

        self.assertIn("requests", requirements)
        self.assertIn('"requests', pyproject)


if __name__ == "__main__":
    unittest.main()
