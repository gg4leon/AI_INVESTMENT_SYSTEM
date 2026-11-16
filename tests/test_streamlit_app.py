"""Smoke test interfaz sin navegador externo y sin Yahoo."""
import unittest

from streamlit.testing.v1 import AppTest


class AppSmokeTest(unittest.TestCase):
    def test_initial_page_renders(self):
        at = AppTest.from_file("streamlit_app.py").run(timeout=30)
        self.assertEqual(len(at.exception), 0, [str(x) for x in at.exception])
        self.assertGreater(len(at.title), 0)


if __name__ == "__main__":
    unittest.main()
